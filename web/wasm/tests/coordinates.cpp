#include "libMems/CompactGappedAlignment.h"
#include "libMems/Interval.h"
#include <iostream>

// A distinct template specialization avoids mixing test and library definitions.
using Alignment = mems::CompactGappedAlignment<mems::AbstractGappedAlignment<mems::HybridAbstractMatch<3>>>;

int main() {
    for (bool source_gaps : {false, true})
    for (bool add_bits : {false, true})
    for (bool reverse : {false, true})
    for (unsigned start : {3u, 510u, 513u, 1020u}) {
        std::string source = "--";
        std::vector<size_t> positions;
        for (unsigned i = 0; i < 1200; ++i) {
            if (source_gaps && i % 3 == 0) source += "---";
            positions.push_back(source.size()); source += 'A';
        }
        source += "--";
        Alignment parent(2, source.size());
        parent.SetAlignment(std::vector<std::string>{source, source});
        for (unsigned s = 0; s < 2; ++s) { parent.SetStart(s, 1); parent.SetLength(1200, s); }
        for (unsigned k = 0; k < positions.size(); ++k)
            if (parent.SeqPosToColumn(0, k + 1) != positions[k]) return 5;

        const std::string target = "--AA-A--AAA-A---AAA--"; // ten residues
        Alignment child(2, target.size());
        child.SetAlignment(std::vector<std::string>{target, std::string(target.size(), 'A')});
        child.SetStart(0, reverse ? -int(start) : int(start)); child.SetLength(10, 0);
        child.SetStart(1, 40); child.SetLength(target.size(), 1);

        std::vector<std::string> expected(2);
        size_t residue = 0, inserted = 0;
        for (char c : target) {
            if (c != '-') {
                if (residue) {
                    size_t gaps = positions[start - 1 + residue] - positions[start - 2 + residue] - 1;
                    expected[0].append(gaps, add_bits ? 'A' : '-');
                    expected[1].append(gaps, '-'); inserted += gaps;
                }
                ++residue;
            }
            expected[0] += c; expected[1] += 'A';
        }
        if (residue != 10) return 1;
        parent.translate(child, 0, 0, add_bits);
        const auto &actual = child.GetAlignment();
        if (child.LeftEnd(0) != positions[start - 1] + 1 || child.LeftEnd(1) != 40 ||
            child.Length(0) != 10 + (add_bits ? inserted : 0) ||
            child.Length(1) != target.size() || child.AlignmentLength() != expected[0].size() ||
            child.Orientation(0) != (reverse ? mems::AbstractMatch::reverse : mems::AbstractMatch::forward))
            return 2;
        for (unsigned s = 0; s < 2; ++s) {
            if (actual[s].size() != expected[s].size()) return 3;
            for (size_t col = 0; col < expected[s].size(); ++col)
                if (actual[s].test(col) != (expected[s][col] != '-')) return 4;
        }
    }
    Alignment match(2, 9);
    match.SetAlignment(std::vector<std::string>{"--AA-A--A", "AAAAAAAAA"});
    match.SetStart(0, 5); match.SetLength(4, 0);
    match.SetStart(1, 10); match.SetLength(9, 1);
    std::vector<mems::AbstractMatch*> matches{&match};
    mems::Interval interval(matches.begin(), matches.end());
    if (interval.GetMatches().size() != 1) return 6;
    std::vector<mems::bitset_t> actual;
    interval.GetAlignment(actual);
    if (actual != match.GetAlignment()) return 7;
    // Preserve the original truncation semantics for surplus bits.
    interval.GetMatches()[0]->SetLength(2, 0);
    interval.GetAlignment(actual);
    mems::bitset_t truncated(9); truncated.set(2); truncated.set(3);
    if (actual[0] != truncated || actual[1] != match.GetAlignment()[1]) return 8;
    // Missing rows must be entirely empty, even if the child has stale bits.
    interval.GetMatches()[0]->SetStart(0, 0);
    interval.GetAlignment(actual);
    if (actual[0].size() != 9 || actual[0].any()) return 9;
    std::cout << "Coordinate translation matches expected gaps, strands, lengths, and origins (32 cases).\n";
    std::cout << "Single-child interval copying preserves full, truncated, and missing rows.\n";
}
