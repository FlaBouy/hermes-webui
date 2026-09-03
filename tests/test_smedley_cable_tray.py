import math
import pytest
from api.smedley_cable_tray import CABLES, ACTIVE, installation, install_adapter


def test_cover_conditions_and_brand_separation():
    params = dict(installation_method='aluminum_ladder_tray', cable_construction='tc_er')
    assert installation(params)['cover_factor'] == 1
    assert installation(dict(params, tray_cover='solid', covered_length_ft=6))['cover_factor'] == 1
    assert installation(dict(params, tray_cover='solid', covered_length_ft=7))['cover_factor'] == .95
    assert installation(dict(params, tray_cover='ventilated', covered_length_ft=70))['cover_factor'] == 1
    for extra in [dict(rung_spacing_in=12),dict(cable_series='allied_custom'),dict(material='aluminum'),dict(tray_cover='solid')]:
        with pytest.raises(ValueError): installation(dict(params, **extra))


def test_adapter_uses_catalog_impedance_and_does_not_leak_between_calls():
    ns = dict(get_ampacity=lambda size,temp:1000, get_impedance=lambda size,conduit:{'R':9,'X':9},
              minimum_size_for_ampacity=lambda amps,temp:'old', _error=lambda error:{'status':'error','error':error})
    def calculation(params):
        return {'status':'ok','result':{'impedance':ns['get_impedance']('4','steel'),'ampacity':ns['get_ampacity']('4',75)},'warnings':[]}
    ns['TOOL_HANDLERS'] = {'/tools/voltage-drop':calculation}
    dispatch = install_adapter(ns)
    result = dispatch('/tools/voltage-drop',dict(cable_construction='tc_er',installation_method='aluminum_ladder_tray',tray_cover='solid',covered_length_ft=7))
    assert result['result']['impedance'] == {'R':.310,'X':.048}
    assert result['result']['ampacity'] == pytest.approx(85*.95)
    assert ACTIVE.get() is None
    assert dispatch('/tools/voltage-drop',{})['result']['impedance']['R'] == 9


def test_catalog_three_phase_voltage_drop_independent_arithmetic():
    r,x = CABLES['4'][1:3]
    drop = math.sqrt(3)*14*1.2*(r*.85 + x*math.sqrt(1-.85**2))
    assert drop == pytest.approx(8.40345, abs=.001)
    assert drop/480*100 < 2
