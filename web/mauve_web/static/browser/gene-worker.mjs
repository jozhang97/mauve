import {Store, MemberCache} from './store.mjs';
import {indexMember} from './core.mjs';
import {analyzeGenes} from './gene-analysis.mjs';

self.onmessage = async ({data: {aid, local, base, options}}) => {
  let store;
  try {
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
    self.postMessage({result});
  } catch (e) { self.postMessage({error: e.message || String(e)}); }
  finally { store?.db.close(); }
};
