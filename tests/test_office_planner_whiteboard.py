"""Contracts for distinct Biggy Workspace vs Visual Planner whiteboard."""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BRAND_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")
VISUAL = (ROOT / "static" / "office-planner" / "visual-ui.js").read_text(encoding="utf-8")
CHART = (ROOT / "static" / "office-planner" / "visual-chart.js").read_text(encoding="utf-8")
APP = (ROOT / "static" / "office-planner" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "office-planner" / "style.css").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "office-planner" / "index.html").read_text(encoding="utf-8")


def test_open_workspace_targets_biggy_workspace_not_visual_planner():
    assert "const BIGGY_WORKSPACE_URL = '/biggy-workspace/';" in BRAND
    assert "BIGGY_VISUAL_WHITEBOARD_URL" in BRAND
    assert "office-planner/index.html?workspace=1" in BRAND
    workspace_line = next(
        line for line in BRAND.splitlines() if "const BIGGY_WORKSPACE_URL" in line
    )
    assert "/biggy-workspace/" in workspace_line
    assert "BIGGY_VISION_ORIGIN" not in workspace_line
    assert "office-planner" not in workspace_line
    assert "plato.tail" not in workspace_line
    whiteboard_assign = BRAND[
        BRAND.index("const BIGGY_VISUAL_WHITEBOARD_URL") : BRAND.index("const BIGGY_VISUAL_WHITEBOARD_URL") + 200
    ]
    assert "office-planner/index.html?workspace=1" in whiteboard_assign
    assert "openBiggyCentralSurface('workspace')" in BRAND
    assert "title.textContent = mode === 'whiteboard' ? 'Visual Planner' : 'Biggy Workspace'" in BRAND


def test_view_button_opens_central_whiteboard_beside_load_revisions():
    assert "button('Load revisions'" in VISUAL
    assert "button('View'" in VISUAL
    assert "argus-open-visual-whiteboard" in VISUAL
    assert "argus-open-visual-whiteboard" in BRAND
    assert "openBiggyVisualWhiteboard" in BRAND
    assert "el('label','Diagram type')" in VISUAL
    assert "el('label','View')" not in VISUAL
    # View is sidebar-only; central whiteboard mode must not re-emit View.
    assert "workspace?[]:[button('View'" in VISUAL or "workspace?[]:[button('View'" in VISUAL.replace(" ", "")


def test_workspace_shell_and_lifecycle_preserved():
    assert "function openBiggyPlannerWorkspace" in BRAND
    assert "function closeBiggyPlannerWorkspace" in BRAND
    assert "argus-planner-workspace-active" in BRAND
    assert "argus-planner-workspace-active" in BRAND_CSS
    assert "Escape" in BRAND
    assert "biggyPlannerCloseWorkspace" in BRAND


def test_whiteboard_mode_still_wires_visual_board():
    assert "workspaceMode=pageParams.get('workspace')==='1'" in APP
    assert "workspace:workspaceMode" in APP
    assert "body.workspace-board" in STYLE
    assert "visual-board-toolbar" in STYLE
    assert "whiteboard-20260911-view" in INDEX
    assert "whiteboard-20260911-view" in APP
    assert "Fit" in VISUAL
    assert "Export SVG" in VISUAL
    assert "argus.visual-plan.active.v1" in VISUAL


def test_flowchart_keeps_full_titles_and_dependency_merge_layout():
    assert "wrapTitleLines" in CHART
    assert "layoutFlowchart" in CHART
    assert "title.slice(0,30)" not in VISUAL
    assert "minWidth='650px'" not in VISUAL
    assert "layoutFlowchart(plan)" in VISUAL
    assert "Smedley Cursor — Local-First Control" in CHART


def test_visual_chart_layout_for_local_first_seven_step_plan():
    script = ROOT / "static" / "office-planner" / "visual-chart.js"
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            f"""
import {{ layoutFlowchart, pickLatestPlan, wrapTitleLines }} from '{script.as_posix()}';
const plan = {{ title: 'Smedley Cursor — Local-First Control', tasks: [
 {{id:'step1',title:'Inspect Cursor model selection and local endpoint support',depends:[]}},
 {{id:'step2',title:'Map ECC handoff and Jarvis/n8n governance interfaces',depends:[]}},
 {{id:'step3',title:'Define GPT-controlled model selection (local-first)',depends:['step1','step2']}},
 {{id:'step4',title:'Prove isolated Cursor assignment uses local model and edits/',depends:['step3']}},
 {{id:'step5',title:'Compare models on bounded tasks',depends:['step4']}},
 {{id:'step6',title:'Rick reviews results and approves minimum required changes',depends:['step5']}},
 {{id:'step7',title:'Apply approved changes, verify model routing, and report res',depends:['step6']}},
]}};
const {{positions, depth}} = layoutFlowchart(plan);
if (depth.get('step1') !== 0 || depth.get('step2') !== 0) throw new Error('parallel roots');
if (depth.get('step3') !== 1) throw new Error('merge into step3');
if (positions.get('step1').x !== positions.get('step2').x) throw new Error('same column');
if (positions.get('step3').x <= positions.get('step1').x) throw new Error('step3 to the right');
const lines = wrapTitleLines(plan.tasks[0].title);
if (!lines.join(' ').includes('Inspect Cursor model selection')) throw new Error('full title');
if (pickLatestPlan([
  {{title:'Other',version:9}},
  {{title:'Smedley Cursor — Local-First Control,',version:1}},
  {{title:'Smedley Cursor — Local-First Control,',version:2}},
]).version !== 2) throw new Error('latest preferred');
console.log('ok');
""",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "ok" in result.stdout


def test_js_syntax_of_touched_office_planner_assets():
    for rel in (
        "static/office-planner/visual-chart.js",
        "static/office-planner/model.js",
        "static/biggy-brand.js",
    ):
        path = ROOT / rel
        checked = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert checked.returncode == 0, f"{rel}: {checked.stderr}"
