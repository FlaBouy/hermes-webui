"""Real Workspace UI with isolated data; shared document-window behavior."""
import os
import sys
import threading
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.getenv('BIGGY_WORKSPACE_REPO', str(ROOT.parent / 'Projects' / 'biggy-workspace')))

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    if not (WORKSPACE / 'biggy_workspace/app.py').is_file():
        pytest.skip('Set BIGGY_WORKSPACE_REPO to run the cross-repository UI integration test')
    sys.path.insert(0, str(WORKSPACE))
    from biggy_workspace.app import AppState, serve
    monkeypatch.setenv('BIGGY_WORKSPACE_RAG_RETRIEVE_URL', 'fixture://workspace-rag')
    state=AppState(db_path=tmp_path/'test.db',credential='synthetic-test-token',host='127.0.0.1',port=0,owner_credential='synthetic-test-owner-password')
    server=serve(state); state.port=server.server_port; thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}'
    finally: server.shutdown();server.server_close();thread.join()


def test_document_stays_in_fullscreen_and_clear_restores_calendar(workspace):
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1280,'height':900})
        errors=[]
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(workspace)
        page.get_by_label('Owner password',exact=True).fill('synthetic-test-owner-password')
        page.get_by_role('button',name='Sign in',exact=True).click()
        expect(page.locator('#app')).to_be_visible()
        assert not errors, errors
        assert page.locator('#error').inner_text() == '', page.locator('#error').inner_text()
        expect(page.get_by_role('searchbox',name='Library search',exact=True)).to_be_enabled()
        if not os.getenv('BIGGY_VIEWER_BASELINE'):
            page.add_script_tag(path=str(ROOT/'static/biggy-document-viewer.js'))
        page.route('**/api/biggy/rag/doc/**',lambda route:route.fulfill(content_type='text/html',body='<h1>Synthetic original document</h1>'))
        calendar=page.locator('.planner-body'); baseline=calendar.bounding_box()['y']
        heading=page.locator('#plan-heading').inner_text()
        page.get_by_role('searchbox',name='Library search',exact=True).fill('manual')
        page.get_by_role('button',name='Search',exact=True).click()
        expect(page.get_by_role('link',name='Open source',exact=True)).to_be_visible()
        assert calendar.bounding_box()['y'] > baseline
        page.evaluate("document.body.insertAdjacentHTML('beforeend', '<button id=fullscreen-test>Full screen</button>'); document.querySelector('#fullscreen-test').onclick=()=>document.documentElement.requestFullscreen()")
        page.locator('#fullscreen-test').click()
        page.get_by_role('link',name='Open source',exact=True).click()
        dialog=page.get_by_role('dialog',name='Document viewer',exact=True)
        expect(dialog).to_be_visible(); assert len(page.context.pages)==1
        assert page.evaluate('!!document.fullscreenElement')
        expect(page.frame_locator('.biggy-document-frame').get_by_text('Synthetic original document')).to_be_visible()
        before=dialog.bounding_box();header=page.get_by_label('Move document window',exact=True).bounding_box()
        page.mouse.move(header['x']+100,header['y']+18);page.mouse.down();page.mouse.move(header['x']+140,header['y']+48);page.mouse.up()
        moved=dialog.bounding_box();assert moved['x']>before['x'] and moved['y']>before['y']
        handle=page.get_by_role('button',name='Resize document window').bounding_box()
        page.mouse.move(handle['x']+10,handle['y']+10);page.mouse.down();page.mouse.move(handle['x']-100,handle['y']-90);page.mouse.up()
        assert dialog.bounding_box()['width'] < moved['width']
        page.get_by_role('button',name='Close document',exact=True).click();expect(dialog).to_have_count(0)
        assert page.evaluate('!!document.fullscreenElement') and len(page.context.pages)==1
        page.get_by_role('button',name='Clear sources',exact=True).click()
        expect(page.get_by_role('link',name='Open source',exact=True)).to_have_count(0)
        assert page.locator('#plan-heading').inner_text()==heading
        assert page.locator('#rag-input').input_value()==''
        assert calendar.bounding_box()['y'] <= baseline+1
        pending=[]
        page.route('**/api/v1/commands',lambda route:pending.append(route))
        page.get_by_role('searchbox',name='Library search',exact=True).fill('late source')
        page.get_by_role('button',name='Search',exact=True).click()
        expect(page.locator('#rag-loading')).to_be_visible()
        page.get_by_role('button',name='Clear sources',exact=True).click()
        assert pending
        pending[0].fulfill(json={'available':True,'result':{'state':'ok','answer':'Late answer','citations':[{'source':'late.pdf','snippet':'Late result','url':'/api/biggy/rag/doc/late.pdf'}]}})
        expect(page.get_by_role('button',name='Search',exact=True)).to_be_enabled()
        expect(page.locator('#rag-answer')).to_be_hidden()
        expect(page.locator('#rag-citations')).to_be_hidden()
        assert page.locator('#plan-heading').inner_text()==heading
        # Other module links in a same-origin iframe share the top-level viewer.
        page.evaluate("const f=document.createElement('iframe');f.id='module-test';f.srcdoc='<a href=\"/api/biggy/rag/doc/other.pdf\">Module document</a>';document.body.append(f)")
        page.frame_locator('#module-test').get_by_role('link',name='Module document').click()
        expect(page.get_by_role('dialog',name='Document viewer',exact=True)).to_be_visible()
        assert len(page.context.pages)==1
        page.get_by_role('button',name='Close document',exact=True).click()
        browser.close()
