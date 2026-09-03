"""Installation adapter for the deterministic electrical service (no model math).

Southwire SPEC45253, tables 1/2, retrieved 2026-09-03. Numeric product facts;
3C copper XHHW-2/CPE TC-ER plus ground. Not interchangeable with Allied stock.
"""
import math
from contextvars import ContextVar

SOURCE = 'https://www.southwire.com/wire-cable/power-control/cu-600-1000v-xlpe-insulation-thermoplastic-cpe-tp-jacket-xhhw-2-ct-rated-sunlight-resistant-for-direct-burial-silicone-free/p/SPEC45253'
TRAY_SOURCE = 'https://www.eaton.com/content/dam/eaton/products/support-systems/cable-management/ct-manual.pdf'
# AWG/kcmil: OD inches, AC R at 75C ohm/kft, X at 60Hz ohm/kft, ampacity 75C/90C.
CABLES = {
    '8': (.784, .786, .052, 50, 55), '6': (.869, .495, .051, 65, 75),
    '4': (.917, .310, .048, 85, 95), '2': (1.045, .195, .045, 115, 130),
    '1/0': (1.261, .122, .044, 150, 170), '3/0': (1.471, .078, .042, 200, 225),
    '4/0': (1.553, .062, .041, 230, 260), '250': (1.726, .053, .041, 255, 290),
    '350': (1.905, .039, .040, 310, 350), '600': (2.425, .025, .039, 420, 475),
    '750': (2.639, .022, .038, 475, 535),
}
ACTIVE = ContextVar('electrical_installation', default=None)


def installation(params):
    method = params.get('installation_method', 'raceway')
    cable = params.get('cable_construction', 'individual')
    if method not in ('raceway', 'aluminum_ladder_tray'):
        raise ValueError('Select raceway or aluminum ladder cable tray.')
    if cable not in ('individual', 'tc_er'):
        raise ValueError('Select individual conductors or TC-ER cable.')
    if method == 'raceway' and cable == 'individual':
        return None
    if cable != 'tc_er':
        raise ValueError('This tray calculation supports multiconductor TC-ER. Individual conductors need their own tray listing and ampacity method.')
    if params.get('cable_series', 'southwire_45253') != 'southwire_45253':
        raise ValueError('Allied requires its exact part-number datasheet; Southwire data will not be substituted.')
    if float(params.get('voltage', 600)) > 1000:
        raise ValueError('Selected Southwire series is rated at most 1000 V; verify ordered cable marking.')
    if str(params.get('material', 'copper')).lower() != 'copper':
        raise ValueError('Selected TC-ER series is copper; aluminum is the tray material, not the conductor.')
    cover = params.get('tray_cover', 'none') if method != 'raceway' else 'none'
    if cover not in ('none', 'ventilated', 'solid'):
        raise ValueError('Tray cover must be none, ventilated, or solid.')
    length = float(params.get('covered_length_ft', 0))
    if not math.isfinite(length) or length < 0 or (cover == 'solid' and length <= 0):
        raise ValueError('Enter the continuous solid-cover length in feet.')
    if method != 'raceway' and float(params.get('rung_spacing_in', 9)) != 9:
        raise ValueError('This aluminum ladder tray profile uses 9-inch rung spacing.')
    if method != 'raceway' and params.get('tray_style', 'ladder') != 'ladder':
        raise ValueError('Aluminum ladder tray requires ladder tray style; the cover is a separate selection.')
    return dict(method=method, cable=cable, series='Southwire SPEC45253',
                tray_material='aluminum' if method != 'raceway' else None,
                rung_spacing_in=9 if method != 'raceway' else None, cover=cover,
                covered_length_ft=length, cover_factor=.95 if cover == 'solid' and length > 6 else 1.0)


def install_adapter(namespace):
    """Wrap the service table lookups, including nested motor/VFD calculations.

    ContextVar scopes installation to one call, never a global mutable override.
    Existing raceway results are untouched when no new installation is selected.
    """
    original_ampacity = namespace['get_ampacity']
    original_impedance = namespace['get_impedance']
    original_minimum = namespace['minimum_size_for_ampacity']

    def ampacity(size, temp=75):
        selected = ACTIVE.get()
        if not selected:
            return original_ampacity(size, temp)
        row = CABLES.get(str(size))
        if row is None:
            return 0  # Candidate not manufactured in the selected series.
        # Keep the service's adopted NEC edition/termination limit. The product
        # page references 2023; do not silently upgrade the project's 2014 basis.
        base = min(original_ampacity(size, temp), row[4 if temp == 90 else 3])
        return base * selected['cover_factor']

    def minimum(amps, temp=75):
        if not ACTIVE.get():
            return original_minimum(amps, temp)
        return next((size for size in CABLES if ampacity(size, temp) >= amps), None)

    def impedance(size, conduit):
        if not ACTIVE.get():
            return original_impedance(size, conduit)
        if str(size) not in CABLES:
            raise ValueError(f'{size} is not in Southwire SPEC45253; available sizes: {", ".join(CABLES)}')
        row = CABLES[str(size)]
        return {'R': row[1], 'X': row[2]}

    namespace.update(get_ampacity=ampacity, minimum_size_for_ampacity=minimum, get_impedance=impedance)

    def dispatch(tool, params):
        try:
            selected = installation(params)
            if not selected:
                return namespace['TOOL_HANDLERS'][tool](params)
            for name in ('amps', 'length_ft', 'voltage', 'parallel_sets', 'num_conductors'):
                if name in params and (not math.isfinite(float(params[name])) or float(params[name]) <= 0):
                    raise ValueError(f'{name} must be a finite positive number.')
            pf = float(params.get('power_factor', .85))
            if not math.isfinite(pf) or not 0 < pf <= 1:
                raise ValueError('Power factor must be greater than zero and at most one.')
            if tool == '/tools/vfd-circuit':
                raise ValueError('SPEC45253 is general power cable, not a validated VFD-output cable selection. Supply drive-approved cable and output-length/filter requirements.')
            if tool == '/tools/conduit-fill' and selected['method'] != 'raceway':
                raise ValueError('For cable tray installation use Cable Tray Fill, not conduit fill.')
            adjusted = dict(params)
            if tool == '/tools/conduit-fill':
                size = str(params.get('tc_er_size', ''))
                count = float(params.get('cable_count', 0))
                if size not in CABLES or not math.isfinite(count) or count < 1 or not count.is_integer():
                    raise ValueError('Select a supported TC-ER conductor size and positive whole-cable count.')
                count = int(count)
                area = math.pi * CABLES[size][0] ** 2 / 4 * count
                key = {1: 'fill_1', 2: 'fill_2'}.get(count, 'fill_3plus')
                conduit = params.get('conduit_type', 'emt')
                trade = params.get('trade_size') or next((s for s in namespace['_CONDUIT_TRADE_SIZES_ORDERED']
                    if s in namespace['NEC_TABLE_CH9_T4'].get(conduit, {})
                    and namespace['get_conduit_areas'](conduit, s)[key] >= area), None)
                if trade is None:
                    raise ValueError('No supported conduit size accommodates these whole TC-ER cables.')
                areas = namespace['get_conduit_areas'](conduit, trade)
                return {'status': 'ok', 'tool': 'conduit-fill', 'installation': selected,
                    'inputs': dict(params), 'result': {'minimum_trade_size': trade, 'trade_size': trade,
                    'solution_found': area <= areas[key], 'pass_fail': 'PASS' if area <= areas[key] else 'FAIL',
                    'conduit_type': conduit, 'total_conductor_area_sqin': round(area, 4),
                    'allowed_area_sqin': areas[key], 'fill_pct': round(area / areas['total_area'] * 100, 2),
                    'fill_limit_pct': {1: 53, 2: 31}.get(count, 40), 'total_conductors': count, 'conductor_size': size},
                    'assumptions': ['Whole jacketed cable OD used; each multiconductor cable counts as one for fill. Integral ground already inside jacket.'],
                    'warnings': ['Any additional separately installed conductors must be included in a separate mixed-fill calculation.'],
                    'code_basis': 'NEC 2014 Chapter 9, Table 1 and Note 9; Table 4 conduit areas.', 'sources': [SOURCE]}
            if tool == '/tools/cable-tray-fill':
                cables = []
                sizes = []
                for item in params.get('cables', []):
                    size = str(item.get('conductor_awg', ''))
                    if size not in CABLES:
                        raise ValueError('For this TC-ER series, each cable row needs conductor_awg (for example "8") and count; generic 3C-10 dimensions are not used.')
                    sizes.append(size)
                    od = CABLES[size][0]
                    cables.append(dict(od_in=od, area_sqin=math.pi * od * od / 4, count=item.get('count', 1)))
                small = all(size in ('8', '6', '4', '2', '1/0', '3/0') for size in sizes)
                large = all(size not in ('8', '6', '4', '2', '1/0', '3/0') for size in sizes)
                if not small and not large:
                    raise ValueError('Mixed multiconductor size groups need the mixed-fill method; do not combine their areas using a single-group rule.')
                adjusted['cables'] = cables
                adjusted['cable_type'] = 'mc_smaller_4/0' if small else 'mc_4/0_plus'
            token = ACTIVE.set(selected)
            try:
                result = namespace['TOOL_HANDLERS'][tool](adjusted)
            finally:
                ACTIVE.reset(token)
            result['installation'] = selected
            result.setdefault('sources', []).extend([SOURCE, TRAY_SOURCE])
            result.setdefault('assumptions', []).extend([
                f"{selected['series']}: 3C copper XHHW-2/CPE TC-ER + ground; AC resistance at 75C, 60Hz reactance. Verify ordered product marking.",
                f"Installation: {selected['method']}; 9-inch rungs when tray; cover={selected['cover']}; ampacity cover factor={selected['cover_factor']}. Base-ampacity fields include this cover factor before ambient correction.",
                'Multiconductor tray fill-area ampacity method, not spaced free-air ampacity. NEC 2014 392.80(A)(1); project edition is unchanged.',
            ])
            result.setdefault('warnings', []).append('Tray bonding/EGC, cable ground size after voltage-drop upsizing, supports, fill, environment and motor starting remain separate design checks; this result is not approval.')
            if tool in ('/tools/feeder-size', '/tools/motor-circuit', '/tools/conductor-sets', '/tools/voltage-drop'):
                result['assumptions'] = [line for line in result['assumptions'] if 'Ch.9 Table 9' not in line and 'Conduit type defaulted' not in line]
            if tool in ('/tools/ocpd-size', '/tools/grounding', '/tools/motor-starter', '/tools/mcc-bucket'):
                result['warnings'].append('Installation recorded. This tool does not by itself establish tray fill, cable ampacity, or voltage-drop compliance.')
            if result.get('status') == 'ok' and tool != '/tools/cable-tray-fill':
                result['code_basis'] = str(result.get('code_basis', '')).replace('Ch.9 Table 9', 'Southwire SPEC45253 R/X data')
            return result
        except (ValueError, TypeError, KeyError) as error:
            return namespace['_error'](str(error))
    return dispatch
