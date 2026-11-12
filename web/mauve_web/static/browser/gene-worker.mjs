import {Store, MemberCache} from './store.mjs';
import {indexMember} from './core.mjs';

self.onmessage = async ({data: {aid, local, base, options}}) => {
  let store;
  try {
    const version = new URL(import.meta.url).searchParams.get('v');
    const moduleURL = name => {
      const url = new URL(name, import.meta.url);
      if (version) url.searchParams.set('v', version);
      return url.href;
    };
    const [{annotateEssentialityReferences}, {analyzeGenes}] = await Promise.all([
      import(moduleURL('./essentiality.mjs')), import(moduleURL('./gene-analysis.mjs')),
    ]);
    let input, load;
    if (local) {
      store = await new Store().open();
      const alignment = await store.get('alignments', aid);
      if (!alignment) throw Error('Alignment not found.');
      input = {genomes: alignment.genomes, sources: await store.all('annotations', store.range(aid)), blocks: await store.all('blocks', store.range(aid))};
      const cache = new MemberCache(store);
      load = (bid, gid) => cache.get(aid, bid, gid);
    } else {
      const get = async path => {
        const response = await fetch(new URL(path, base));
        if (!response.ok) throw Error((await response.json()).detail || 'Could not load analysis data.');
        return response.json();
      };
      input = await get(`api/alignments/${aid}/gene-input`);
      const cache = new MemberCache({get: async (_, [, bid, gid]) => indexMember(await get(`api/alignments/${aid}/blocks/${bid}/gene-member/${gid}`))});
      load = (bid, gid) => cache.get(aid, bid, gid);
    }
    const result = await analyzeGenes(input, load, options, progress => self.postMessage({progress}));
    try {
      const snapshots = await Promise.all(['ecoli', 'hpylori', 'bsubtilis'].map(async organism => {
        const response = await fetch(new URL(`../essentiality-${organism}.json`, import.meta.url));
        if (!response.ok) throw Error(`snapshot request failed (HTTP ${response.status})`);
        return response.json();
      }));
      annotateEssentialityReferences(result, snapshots);
    } catch (error) {
      result.essentiality_error = `Essentiality unavailable: ${error.message}`;
    }
    self.postMessage({result});
  } catch (e) { self.postMessage({error: e.message || String(e)}); }
  finally { store?.db.close(); }
};
