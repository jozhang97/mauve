"""Selected-block annotation queries respect each member's native coordinates."""
from io import StringIO
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import SeqFeature, SimpleLocation, CompoundLocation
from Bio.SeqRecord import SeqRecord
from test_gene_analysis import analysis_site, site, browser, browser_app


def test_selected_block_annotations_per_genome_pagination_and_switching(analysis_site, browser):
    mode, url = analysis_site
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    dna = 'ACGT' * 25
    xmfa = f'> 1:101-200 + first.fa\n{dna}\n> 2:1101-1200 - second.fa\n{dna}\n=\n'
    xmfa += ''.join(f'> {gid}:{start}-{start+99} + genome{gid}.fa\n{dna}\n' for gid, start in [(1, 501), (2, 1501), (3, 101)]) + '=\n'
    page.locator('#file').set_input_files({'name': 'block-genes.xmfa', 'mimeType': 'text/plain', 'buffer': xmfa.encode()})
    page.wait_for_function('state.alignment?.genomes.length === 3')
    def feature(name, start, end):
        return SeqFeature(SimpleLocation(start-1, end, strand=1), type='CDS', qualifiers={'gene': [name]})
    annotations = [
        [feature('first_block1', 150, 160), feature('boundary', 190, 220), feature('first_block2', 550, 560),
         feature('outside', 350, 360),
         SeqFeature(CompoundLocation([SimpleLocation(49, 60, strand=1), SimpleLocation(249, 260, strand=1)]), type='CDS', qualifiers={'gene': ['span_only']}),
         *[feature(f'pagination_{i}', 151, 152) for i in range(510)]],
        [feature('second_block1', 1150, 1160), feature('wrong_reference_coordinates', 150, 160), feature('second_block2', 1550, 1560)],
        [feature('third_block2', 150, 160)],
    ]
    for gid, features in enumerate(annotations, 1):
        record = SeqRecord(Seq('ACGT' * 500), id='chr', name='chr', annotations={'molecule_type': 'DNA', 'topology': 'circular'})
        record.features = features
        out = StringIO(); SeqIO.write(record, out, 'genbank')
        page.locator('#annotation-genome').select_option(str(gid))
        page.locator('#annotation-file').set_input_files({'name': f'g{gid}.gbk', 'mimeType': 'text/plain', 'buffer': out.getvalue().encode()})
        page.wait_for_function(f'state.sources.length === {gid}')
    assert page.locator('svg .feature').count() == 0
    page.locator('#reset').click()
    page.evaluate('selectBlock(1)')
    page.wait_for_function('state.features.length === 513')
    features = page.evaluate('state.features.map(f => ({name:f.name, genome:f.genome_id}))')
    assert sum(f['genome'] == 1 for f in features) == 512
    assert [f['name'] for f in features if f['genome'] == 2] == ['second_block1']
    assert not any(f['genome'] == 3 for f in features)
    assert not {'outside', 'span_only', 'wrong_reference_coordinates'} & {f['name'] for f in features}
    assert page.locator('svg .feature').count() == 513
    boundary = page.locator('polygon.feature[aria-label^="boundary,"]')
    assert 'clipped to block 1' in boundary.locator('title').text_content()
    block = page.locator('rect.block[aria-label^="Block 1, sequence 1,"]').bounding_box()
    arrow = boundary.bounding_box()
    assert arrow['x'] + arrow['width'] <= block['x'] + block['width'] + 1
    page.locator('#region').fill('101-200'); page.locator('#region-form button').click()
    assert page.evaluate('state.features.length') == 513  # Zoom retains selected-block data.
    assert page.locator('svg .feature[aria-label^="second_block1,"]').count() == 0
    page.locator('#reset').click()
    page.evaluate('selectBlock(2)')
    page.wait_for_function('state.features.length === 3')
    assert set(page.evaluate('state.features.map(f => f.name)')) == {'first_block2', 'second_block2', 'third_block2'}
    assert page.locator('svg .feature').count() == 3
    # Search selects the block containing a feature instead of drawing it under an unrelated block.
    page.locator('#annotation-genome').select_option('2')
    page.locator('#gene-query').fill('second_block1'); page.locator('#feature-search button').click()
    page.locator('#feature-results button').first.click()
    page.wait_for_function('state.selected === 1 && state.features.length === 513')
    assert page.locator('svg .feature[aria-label^="second_block1,"]').count() == 1
    # A newer block selection wins even while annotation requests are in flight.
    page.evaluate('async () => { await selectBlock(2); await selectBlock(1); await selectBlock(2); }')
    page.wait_for_function('state.selected === 2 && state.features.length === 3')
    assert set(page.evaluate('state.features.map(f => f.name)')) == {'first_block2', 'second_block2', 'third_block2'}
    # Align mode translates all layers using actual corresponding bases.
    page.locator('#reset').click()
    page.locator('#display-settings summary').click()
    page.locator('#align-tracks').check()
    assert page.evaluate('trackOffset(2) - trackOffset(1)') == 1000
    assert page.evaluate('trackOffset(3) - trackOffset(1)') == -400
    starts = page.locator('rect.block').evaluate_all("nodes => nodes.filter(n => n.mauveBlockId === 2).map(n => Number(n.getAttribute('x')))")
    assert max(starts) - min(starts) < 0.001
    # Labels and gene arrows retain each genome's native positions.
    arrows = page.locator('svg .feature').evaluate_all("nodes => nodes.map(n => n.getBBox().x)")
    assert max(arrows) - min(arrows) < 0.001
    page.locator('#align-tracks').uncheck()
    assert page.evaluate('trackOffset(2)') == 0
    page.locator('#align-tracks').check()
    # Click a reversed block: matched bases line up without flipping the genome.
    page.locator('rect.block[aria-label^="Block 1, sequence 1,"]').click()
    page.wait_for_function('state.selected === 1 && state.features.length === 513')
    assert page.evaluate("state.detail.members[0].positions[0] - trackOffset(1) === state.detail.members[1].positions[0] - trackOffset(2)")
    assert page.evaluate('trackOffset(3)') == -400  # Absent member retains its view.
    offsets = page.evaluate('Array.from(state.trackOffsets)')
    page.locator('#zoom-in').click()
    assert page.evaluate('Array.from(state.trackOffsets)') == offsets
    page.locator('#align-tracks').uncheck()
    assert page.evaluate('trackOffset(1) === 0 && trackOffset(2) === 0 && trackOffset(3) === 0')
    # Circular tracks continue through the origin instead of leaving blank space.
    page.locator('#align-tracks').check()
    page.evaluate('() => { state.trackOffsets.clear(); setRange(1950, 2250, false); }')
    assert page.evaluate('state.end') == 2250
    wrapped = page.locator('rect.block[aria-label^="Block 1, sequence 1,"]')
    assert wrapped.count() == 1
    assert wrapped.evaluate('e => e.mauveCopy') == 2000
    assert page.locator('.chromosome-origin[data-genome="1"]').count() == 1
    before_wrap_x = wrapped.evaluate("e => Number(e.getAttribute('x'))")
    wrapped.click()
    page.wait_for_function('state.selected === 1 && state.features.length === 513')
    assert page.evaluate('state.detail.members.find(m => m.genome_id === 1).positions[0]') in range(101, 201)
    assert abs(wrapped.evaluate("e => Number(e.getAttribute('x'))") - before_wrap_x) < 0.001
    assert page.locator('svg .feature[aria-label^="first_block1,"]').count() == 1
    page.wait_for_function('state.profile?.block_id === 1 || document.querySelectorAll(".identity-window").length > 0')
    assert page.locator('.identity-window').count() > 0
    assert page.locator('.page-window').count() > 0
    # Panning backwards also wraps; native labels never become negative.
    page.evaluate('() => { state.trackOffsets.clear(); setRange(-1950, -1750, false); }')
    assert page.locator('rect.block[aria-label^="Block 1, sequence 1,"]').evaluate('e => e.mauveCopy') == -2000
    assert page.evaluate('nativePosition(-1, 1)') == 1999
    # Range controls use native reference coordinates across the origin.
    assert page.locator('#region').input_value() == '50-250'
    page.locator('#region').fill('1950-250')
    page.locator('#region-form button').click()
    assert page.locator('#region').input_value() == '1950-250'
    assert 'REF #1' in page.locator('#range').inner_text()
    assert 'crosses origin' in page.locator('#range').inner_text()
    assert page.evaluate('state.end - state.start + 1') == 301
    assert page.evaluate("""() => {
      const svg = document.querySelector('#tracks svg'), width = svg.viewBox.baseVal.width;
      return [...svg.querySelectorAll('.genome-coordinate')].every(tick => {
        const gid = Number(tick.dataset.genome);
        const view = state.start + (Number(tick.getAttribute('x')) - 180) / (width - 206) * (state.end - state.start + 1);
        return Number(tick.textContent.replaceAll(',', '')) === nativePosition(Math.round(view + trackOffset(gid)), gid);
      });
    }""")
    wrapped = page.locator('rect.block[aria-label^="Block 1, sequence 1,"]')
    wrapped.click(position={'x': 5, 'y': 9})
    page.wait_for_function('state.detail?.members.find(m => m.genome_id === 1)?.positions[0] < 120')
    assert page.locator('#region').input_value() == '1950-250'
    page.locator('#zoom-selected').click()
    assert page.evaluate('state.end - state.start + 1') < 300
    assert page.evaluate("""() => state.blocks.find(b => b.id === state.selected).members.every(m => {
      const copies = trackCopies(m.start, m.end, m.genome_id);
      return copies.some(copy => m.start + copy - trackOffset(m.genome_id) >= state.start && m.end + copy - trackOffset(m.genome_id) <= state.end);
    })""")
    page.evaluate('() => { state.trackOffsets.clear(); setRange(-1950, -1750, false); }')
    # Unannotated/linear records must not be silently treated as circular.
    page.evaluate("() => { state.sources.find(s => s.genome_id === 2).metadata.records[0].topology = 'linear'; render(); }")
    assert page.evaluate('circularLength(2)') == 0
    assert page.evaluate('trackCopies(1101, 1200, 2)') == []
    page.locator('#align-tracks').uncheck()
    assert page.evaluate('state.start >= 1 && state.end <= state.max')
    assert not errors
    page.close()


def test_circular_unequal_lengths_one_turn_and_boundary_clicks(analysis_site, browser):
    mode, url = analysis_site
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    dna = 'ACGT' * 25
    xmfa = f'> 1:101-200 + short.fa\n{dna}\n> 2:1301-1400 + long.fa\n{dna}\n=\n'
    xmfa += f'> 1:901-1000 + short.fa\n{dna}\n> 2:901-1000 + long.fa\n{dna}\n=\n'
    page.locator('#file').set_input_files({'name': 'unequal.xmfa', 'mimeType': 'text/plain', 'buffer': xmfa.encode()})
    page.wait_for_function('state.alignment?.genomes.length === 2')
    for gid, length, start in [(1, 1000, 110), (2, 1400, 1310)]:
        record = SeqRecord(Seq('ACGT' * (length // 4)), id='chr', name='chr', annotations={'molecule_type': 'DNA', 'topology': 'circular'})
        record.features = [SeqFeature(SimpleLocation(start - 1, start + 10, strand=1), type='CDS', qualifiers={'gene': [f'gene{gid}']})]
        out = StringIO(); SeqIO.write(record, out, 'genbank')
        page.locator('#annotation-genome').select_option(str(gid))
        page.locator('#annotation-file').set_input_files({'name': f'g{gid}.gbk', 'mimeType': 'text/plain', 'buffer': out.getvalue().encode()})
        page.wait_for_function(f'state.sources.length === {gid}')
    page.evaluate('selectBlock(1)')
    page.wait_for_function('state.features.length === 2')
    page.locator('#display-settings summary').click()
    page.locator('#align-tracks').check()
    assert page.evaluate('state.end - state.start + 1') == 1400
    assert page.locator('.feature[data-genome="1"]').count() == 1
    assert page.locator('.feature[data-genome="2"]').count() == 1
    assert page.evaluate('trackEnd(1) - state.start + 1') == 1000
    assert page.evaluate('trackEnd(2) - state.start + 1') == 1400
    assert page.locator('#region').input_value() == '1-1000'
    assert 'more than one turn' not in page.locator('#range').inner_text()
    # Across rotations and viewport sizes, every displayed base occurs at most once.
    assert page.evaluate("""() => {
      const saved = [state.start, state.end, new Map(state.trackOffsets)];
      try {
        for (const gid of [1, 2]) for (const shift of [-2401, -1000, -1, 0, 99, 1400, 2801])
          for (const start of [-2000, -1, 1, 115, 950, 1501]) for (const span of [1, 100, 1000, 1400]) {
            state.start = start; state.end = start + span - 1; state.trackOffsets.set(gid, shift);
            const length = circularLength(gid);
            const pieces = trackCopies(1, length, gid).map(copy => [
              Math.max(1, start + shift - copy), Math.min(length, trackEnd(gid) + shift - copy)
            ]).sort((a,b) => a[0]-b[0]);
            if (pieces.reduce((sum, p) => sum+p[1]-p[0]+1, 0) !== Math.min(span, length)) return false;
            if (pieces.some((p,i) => i && pieces[i-1][1] >= p[0])) return false;
          }
        return true;
      } finally { [state.start, state.end, state.trackOffsets] = saved; }
    }""")
    # A feature cut by the viewing seam may have two fragments, never repeated bases.
    page.evaluate('() => { state.trackOffsets.clear(); setRange(115, 1514, false); }')
    fragments = page.locator('.feature[data-genome="1"]').evaluate_all('nodes => nodes.map(n => [Number(n.dataset.visibleStart), Number(n.dataset.visibleEnd)])')
    assert sorted(fragments) == [[110, 114], [115, 120]]
    assert sum(end - start + 1 for start, end in fragments) == 11
    assert all('continues beyond this edge' in title for title in page.locator('.feature[data-genome="1"] title').all_text_contents())
    # The exact clicked copy is used, even in the final half of the last base.
    page.evaluate('() => { state.trackOffsets.clear(); setRange(950, 1049, false); }')
    page.locator('#show-identity').uncheck()
    block = page.locator('rect.block[aria-label^="Block 2, sequence 1,"]')
    page.evaluate('''() => {
      const svg = document.querySelector('#tracks svg');
      const node = [...svg.querySelectorAll('rect.block')].find(n => n.mauveBlockId === 2 && n.mauveMember.genome_id === 1);
      const point = svg.createSVGPoint();
      point.x = 180 + (1000.8 - state.start) / (state.end - state.start + 1) * (svg.viewBox.baseVal.width - 206);
      point.y = Number(node.getAttribute('y')) + 9;
      const screen = point.matrixTransform(svg.getScreenCTM());
      node.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:screen.x, clientY:screen.y}));
    }''')
    page.wait_for_function('state.selected === 2')
    assert page.evaluate('state.detail.members.find(m => m.genome_id === 1).positions[0]') == 1000
    block.press('Enter')
    page.wait_for_function('state.detail.members.find(m => m.genome_id === 1).positions[0] === 950')
    page.locator('#reset').click()
    assert page.locator('rect.block[data-block-id="1"]').count() == 2
    assert page.evaluate('state.trackOffsets.size') == 0
    assert not errors
    page.close()


def test_align_click_searches_past_gap_page(analysis_site, browser):
    mode, url = analysis_site
    page = browser.new_page()
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    xmfa = '> 1:1-1000 + anchor.fa\n' + 'A' * 1000 + '\n> 2:1001-1300 + gap.fa\n' + '-' * 700 + 'A' * 300 + '\n=\n'
    xmfa += '> 1:1501-1510 + anchor.fa\nAAAAAAAAAA\n> 2:2001-2010 + gap.fa\nAAAAAAAAAA\n=\n'
    page.locator('#file').set_input_files({'name': 'long-gap.xmfa', 'mimeType': 'text/plain', 'buffer': xmfa.encode()})
    page.wait_for_function('state.blocks.length === 2')
    page.evaluate('''async () => {
      document.getElementById('align-tracks').checked = true;
      state.trackOffsets.set(2, 900);
      await selectBlock(1, 0, {genome_id: 1, position: 101, viewPosition: 101}, false, true);
    }''')
    assert page.evaluate('trackOffset(2)') == 300
    assert page.evaluate('state.detail.members[0].positions[0]') == 101
    assert page.evaluate('state.detail.members[1].positions.every(p => p === null)')
    assert page.evaluate('701 - trackOffset(1) === 1001 - trackOffset(2)')
    # Enabling the mode on an all-gap reference page uses another anchor.
    page.evaluate("""async () => {
      state.reference = 2;
      state.trackOffsets.clear();
      await alignTracks(state.detail);
    }""")
    assert page.evaluate('trackOffset(2)') == 300
    # Aborting an asynchronous gap search leaves selection and export in sync.
    page.evaluate('selectBlock(2)')
    page.evaluate("""() => {
      const original = api;
      let delay = true;
      api = async (path, ...args) => {
        if (delay && path.includes('/blocks/1?') && path.includes('limit=500')) {
          delay = false;
          await new Promise(resolve => { window.releaseGapLookup = resolve; });
        }
        return original(path, ...args);
      };
      window.pendingGapSelection = selectBlock(1, 0, {genome_id:1,position:101}, false, true)
        .finally(() => { api = original; });
    }""")
    page.wait_for_function("typeof window.releaseGapLookup === 'function'")
    page.evaluate('fitAllTracks()')
    page.evaluate('async () => { window.releaseGapLookup(); await window.pendingGapSelection; }')
    assert page.evaluate('state.selected') == 2
    assert page.locator('#export-fasta').get_attribute('href').endswith('/blocks/2/fasta')
    page.close()


def test_links_cover_both_circular_fragments(analysis_site, browser):
    mode, url = analysis_site
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    page.goto(url)
    if mode == 'static':
        page.wait_for_function('window.mauveReady === true')
    page.wait_for_function("typeof render === 'function'")
    result = page.evaluate('''() => {
      state.alignment = {genomes: [1,2].map(id => ({id,name:`G${id}`,extent:100}))};
      state.reference = 1; state.order = [1,2]; state.hidden.clear();
      state.start = 1; state.end = 100; state.max = 100;
      state.selected = null; state.detail = null; state.profile = null; state.features = [];
      state.sources = [1,2].map(genome_id => ({genome_id,metadata:{records:[{name:'chr',start:1,end:100,topology:'circular'}]}}));
      state.blocks = [{id:1,columns:20,members:[1,2].map(genome_id=>({genome_id,start:1,end:20,strand:'+'}))}];
      clearBlockFilters(); document.getElementById('align-tracks').checked = true;
      document.getElementById('links').checked = true;
      document.getElementById('welcome').hidden = true; document.getElementById('explorer').hidden = false;
      state.trackOffsets = new Map([[1,0],[2,10]]); render();
      const svg = document.querySelector('#tracks svg');
      const paths = [...svg.querySelectorAll('.alignment-links path')];
      const scale = (svg.viewBox.baseVal.width - 206) / 100;
      return {count:paths.length, spans:paths.map(p => {
        const nums=p.getAttribute('d').match(/-?[\\d.]+/g).map(Number);
        return Math.abs(nums[2]-nums[0])/scale;
      })};
    }''')
    assert result['count'] == 2
    assert abs(sum(result['spans']) - 20) < 0.001
    page.close()
