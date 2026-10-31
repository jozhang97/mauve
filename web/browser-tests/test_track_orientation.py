"""Track orientation preserves native coordinates through all display layers."""
from io import StringIO
import pytest
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation
from Bio.SeqRecord import SeqRecord
from test_gene_analysis import analysis_site, site, browser, browser_app


@pytest.mark.parametrize("core_only", [False, True])
def test_track_orientation(analysis_site, browser, core_only):
    mode, url = analysis_site
    page = browser.new_page(viewport={'width':1440,'height':1100})
    errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url)
    if mode == 'static': page.wait_for_function('window.mauveReady === true')
    xmfa='> 1:101-200 + first.fa\n'+'A'*100+'\n> 2:1101-1200 - second.fa\n'+'A'*100+'\n=\n'
    xmfa+='> 1:501-600 + first.fa\n'+'A'*100+'\n> 2:1501-1600 + second.fa\n'+'T'*100+'\n=\n'
    page.locator('#file').set_input_files({'name':'orient.xmfa','mimeType':'text/plain','buffer':xmfa.encode()})
    page.wait_for_function('state.blocks.length === 2')
    for gid,base,start,end,strand in [(1,'A',150,160,1),(2,'T',1141,1151,-1)]:
        record=SeqRecord(Seq(base*2000),id='chr',name='chr',annotations={'molecule_type':'DNA','topology':'circular'})
        record.features=[SeqFeature(SimpleLocation(start-1,end,strand=strand),type='CDS',qualifiers={'gene':[f'gene{gid}']})]
        out=StringIO();SeqIO.write(record,out,'genbank')
        page.locator('#annotation-genome').select_option(str(gid))
        page.locator('#annotation-file').set_input_files({'name':f'g{gid}.gbk','mimeType':'text/plain','buffer':out.getvalue().encode()})
        page.wait_for_function(f'state.sources.length === {gid}')
    page.evaluate('selectBlock(1)');page.wait_for_function('state.features.length === 2')
    page.locator('#display-settings summary').click()
    if core_only:
        page.locator('#core-genes-only').check()
        page.wait_for_function('window.mauveGeneAnalysis?.result')
        assert page.evaluate('visibleBlocks().map(b=>b.id)') == [1]
    page.locator('#orient-tracks').check()
    page.wait_for_function('trackDirection(2) === -1')
    assert page.locator('#align-tracks').is_checked()
    assert page.locator('.reversed-view[data-genome="2"]').count()==1
    if core_only:
        offsets = page.evaluate('[...state.trackOffsets]')
        page.evaluate('setRange(501, 600, false)')
        page.evaluate('refreshCoreGenes()')
        assert page.evaluate('[...state.trackOffsets]') == offsets
        assert page.evaluate('trackDirection(2)') == -1
        assert page.locator('.block').count() > 0
    page.locator('#zoom-selected').click()
    assert page.locator('#core-genes-only').is_checked() == core_only
    # Re-selecting the current block from the list must restore alignment after Fit all.
    page.locator('#reset').click()
    page.locator('#block-list button').filter(has=page.get_by_text('Block 1', exact=True)).click()
    page.wait_for_function('Math.abs(trackOffset(2)-trackOffset(1)) > 0')
    page.locator('#zoom-selected').click()
    xs=page.locator('rect.block[data-block-id="1"]').evaluate_all("nodes=>nodes.map(n=>Number(n.getAttribute('x')))")
    assert len(xs)==2 and abs(xs[0]-xs[1])<.001
    arrows=page.locator('.feature').evaluate_all("nodes=>nodes.map(n=>n.getAttribute('points').split(' ').map(p=>Number(p.split(',')[0])))")
    assert len(arrows)==2 and all(abs(a-b)<.001 for a,b in zip(*arrows))
    if core_only:
        geometry = page.evaluate('({directions:[...state.trackDirections],offsets:[...state.trackOffsets],start:state.start,end:state.end})')
        page.locator('#core-genes-only').uncheck()
        page.locator('#core-genes-only').check()
        assert page.evaluate('({directions:[...state.trackDirections],offsets:[...state.trackOffsets],start:state.start,end:state.end})') == geometry
        assert page.locator('.feature').evaluate_all("nodes=>nodes.map(n=>n.getAttribute('points').split(' ').map(p=>Number(p.split(',')[0])))") == arrows

    ticks=[int(t.replace(',','')) for t in page.locator('.genome-coordinate[data-genome="2"]').all_text_contents()]
    assert ticks==sorted(ticks,reverse=True)
    page.evaluate('''() => {
      const svg=document.querySelector('#tracks svg');
      const node=[...svg.querySelectorAll('rect.block')].find(n=>n.mauveBlockId===1&&n.mauveMember.genome_id===2);
      const point=svg.createSVGPoint(), view=orientedBase(1163,2)+node.mauveCopy-trackOffset(2)+.8;
      point.x=180+(view-state.start)/(state.end-state.start+1)*(svg.viewBox.baseVal.width-206);
      point.y=Number(node.getAttribute('y'))+9;
      const screen=point.matrixTransform(svg.getScreenCTM());
      node.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:screen.x,clientY:screen.y}));
    }''')
    page.wait_for_function('state.detail.members.find(m=>m.genome_id===2).positions[0] === 1163')
    assert page.evaluate('state.detail.members.find(m=>m.genome_id===1).positions[0]')==138
    page.locator('#reference-genome').select_option('2')
    page.wait_for_function('trackDirection(1) === -1 && trackDirection(2) === 1')
    page.wait_for_function("document.querySelector('.sequence-row[data-genome=\"2\"] .base').textContent === 'T'")
    columns=page.locator('.sequence-row[data-genome="2"] .base').evaluate_all('nodes=>nodes.map(n=>Number(n.dataset.column))')
    assert columns==sorted(columns,reverse=True)
    page.evaluate('() => setRange(-500,1499,false)')
    assert page.evaluate('''() => [1,2].every(gid=> {
      const pieces=trackCopies(1,2000,gid).map(copy=>nativeWindow(gid,copy)).map(([a,b])=>[Math.max(1,a),Math.min(2000,b)]).sort((a,b)=>a[0]-b[0]);
      return pieces.reduce((n,[a,b])=>n+b-a+1,0)===2000 && pieces.every((p,i)=>!i||pieces[i-1][1]<p[0]);
    })''')
    page.locator('#orient-tracks').uncheck()
    page.wait_for_function('trackDirection(1) === 1 && trackDirection(2) === 1')
    assert page.locator('.reversed-view').count()==0
    page.locator('#orient-tracks').check()
    if core_only: page.locator('#core-genes-only').uncheck()
    page.locator('#reset').click()
    page.evaluate(r'''() => {
      const original = api;
      api = async (path, options) => {
        const value = await original(path, options);
        if (/\/blocks\/2\?/.test(path)) await new Promise(resolve=>setTimeout(resolve,250));
        return value;
      };
    }''')
    page.locator('rect.block[data-block-id="2"]').first.dblclick()
    page.wait_for_function('state.selected === 2', timeout=3000)
    assert page.evaluate('trackDirection(1) === 1 && trackDirection(2) === 1')
    # A slower, older request must not overwrite the last block chosen.
    page.evaluate('Promise.all([selectBlock(2), selectBlock(1)])')
    assert page.evaluate('state.selected') == 1
    assert page.evaluate('trackDirection(1) === -1 && trackDirection(2) === 1')
    for bid in [2, 1, 2, 1]:
        page.locator('#block-list button').filter(has=page.get_by_text(f'Block {bid}', exact=True)).click()
        page.wait_for_function('(id)=>state.selected===id', arg=bid)
        assert page.evaluate('trackDirection(1)') == (-1 if bid == 1 else 1)
        assert page.evaluate('trackDirection(2)') == 1
    page.locator('#align-tracks').uncheck()
    assert not page.locator('#orient-tracks').is_checked()
    assert not errors,errors
    page.close()
