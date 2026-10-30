"""Exact ungapped coverage fast path; experimental until differential validation."""
def candidate(text):
    start = text.index('void SingleCopyDistanceMatrix(')
    end = text.index('\n\tTransformDistanceIdentity(distance);', start)
    end = text.index('}', end) + 1
    part = text[start:end]
    old = 'std::pair< bitset_t, bitset_t >'
    assert part.count(old) == 2
    part = part.replace(old, 'std::pair< MauveCoverageBitmap, MauveCoverageBitmap >')
    marker = '\t\tiv_list[ivI]->GetAlignment(aln_table);\n}'
    assert marker in part
    part = part.replace(marker, marker + '''
        std::vector<bool> ungapped(seq_count);
        for (uint s = 0; s < seq_count; ++s) ungapped[s] = aln_table[s].all();''')
    marker = '\t\t\t\tfor( size_t colI = 0; colI < aln_table[seqI].size(); ++colI )'
    assert marker in part
    part = part.replace(marker, '''                if (ungapped[seqI] && ungapped[seqJ] && aln_table[seqI].size() == aln_table[seqJ].size()) {
                    const size_t len = aln_table[seqI].size();
                    const size_t first_i = o_i == AbstractMatch::forward ? seqI_pos - 1 : seqI_pos - len;
                    const size_t first_j = o_j == AbstractMatch::forward ? seqJ_pos - 1 : seqJ_pos - len;
                    pair_comp[seqI][seqJ].first.set_range(first_i, len);
                    pair_comp[seqI][seqJ].second.set_range(first_j, len);
                    continue;
                }
''' + marker)
    return text[:start] + part + text[end:]
