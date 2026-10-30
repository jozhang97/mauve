#include "coverage_bitmap.h"
#include "libMems/ProgressiveAligner.h"
#include "distance_variants.h"
#include "libMUSCLE/muscle.h"
#include "libMUSCLE/profile.h"
#include "libMUSCLE/pwpath.h"
#include <chrono>
#include <cstdio>
#include <cstring>
#include <memory>
#ifndef __EMSCRIPTEN__
__thread unsigned mauve_thread_index = 0;
#endif
using Clock = std::chrono::steady_clock;
namespace muscle { SCORE NWSmall(const ProfPos*, unsigned, const ProfPos*, unsigned, PWPath&); }

double milliseconds(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now()-start).count();
}
int main() {
    using namespace mems;
    // Exhaust all small ranges, including zero length, word boundaries, and overlaps.
    for (size_t size : {0u, 1u, 63u, 64u, 65u, 129u})
    for (size_t begin=0; begin<=size; ++begin)
    for (size_t count=0; count<=size-begin; ++count) {
        MauveCoverageBitmap bits; bits.resize(size);
        std::vector<bool> expected(size);
        for (size_t i=0; i<size; i+=7) { bits.set(i); expected[i]=true; }
        bits.set_range(begin,count);
        for (size_t i=begin;i<begin+count;++i) expected[i]=true;
        size_t sum=0; for (bool bit:expected) sum+=bit;
        if (bits.count()!=sum) return 2;
    }
    // Differential distance matrices: gapped rows, overlaps, reverse strands,
    // missing genomes, partial final words, and empty match lists.
    uint32_t random=37;
    auto draw=[&](){random=random*1664525u+1013904223u;return random;};
    for (unsigned trial=0;trial<100;++trial) {
        std::vector<std::unique_ptr<genome::gnSequence>> owned;
        std::vector<genome::gnSequence*> seqs;
        for (unsigned i=0;i<4;++i) {owned.emplace_back(new genome::gnSequence(std::string(1027,'A')));seqs.push_back(owned.back().get());}
        std::vector<std::unique_ptr<GappedAlignment>> storage;
        std::vector<AbstractMatch*> matches;
        for (unsigned iv=0;iv<trial%10;++iv) {
            const unsigned cols=1+draw()%250;
            storage.emplace_back(new GappedAlignment(4,cols));
            auto &aln=*storage.back();
            std::vector<std::string> rows(4,std::string(cols,'A'));
            for(unsigned s=0;s<4;++s) {
                if(trial%3) for(char &c:rows[s]) if(draw()%5==0)c='-';
            }
            aln.SetAlignment(rows);
            for(unsigned s=0;s<4;++s) {
                size_t length=std::count(rows[s].begin(),rows[s].end(),'A');
                int start=1+draw()%700;
                aln.SetStart(s, draw()%2 ? start : -start);
                aln.SetLength(length,s);
                if(draw()%9==0) {aln.SetStart(s,0);aln.SetLength(0,s);}
            }
            matches.push_back(&aln);
        }
        NumericMatrix<double> reference, candidate;
        SingleCopyDistanceReference(matches,seqs,reference);
        SingleCopyDistanceCandidate(matches,seqs,candidate);
        for(unsigned i=0;i<4;++i)for(unsigned j=0;j<4;++j)
            if(reference(i,j)!=candidate(i,j))return 3;
    }
    std::puts("VALIDATION coverage 100 matrices and exhaustive range boundaries passed");
    std::vector<std::unique_ptr<genome::gnSequence>> owned;
    std::vector<genome::gnSequence*> seqs;
    for(unsigned i=0;i<32;++i){owned.emplace_back(new genome::gnSequence(std::string(100000,'A')));seqs.push_back(owned.back().get());}
    std::vector<std::unique_ptr<Match>> storage;
    std::vector<AbstractMatch*> matches;
    for(unsigned i=0;i<20;++i){
        storage.emplace_back(new Match(32));
        for(unsigned s=0;s<32;++s){storage.back()->SetStart(s,(s%2?-1:1)*(1+int(i*4000)));storage.back()->SetLength(20000,s);}
        matches.push_back(storage.back().get());
    }
    for(unsigned rep=0;rep<3;++rep) for(unsigned order=0;order<2;++order){
        bool candidate=(rep%2?1-order:order);
        NumericMatrix<double> result;
        auto start=Clock::now();
        if(candidate)SingleCopyDistanceCandidate(matches,seqs,result);
        else SingleCopyDistanceReference(matches,seqs,result);
        double ms=milliseconds(start),checksum=0;
        for(unsigned i=0;i<32;++i)for(unsigned j=0;j<32;++j)checksum+=result(i,j);
        std::printf("KERNEL coverage_%s %u %.6f %.17g\n",candidate?"ranges":"reference",rep,ms,checksum);
    }
    using namespace muscle;
    g_PPScore.get()=PPSCORE_SPN;g_scoreCenter.get()=0.5f;g_TermGaps.get()=TERMGAPS_Half;g_scoreGapExtend.get()=-0.25f;
    for(unsigned length:{128u,512u,1024u}) {
        std::vector<ProfPos>a(length),b(length);
        for(auto *rows:{&a,&b})for(auto &p:*rows){
            for(unsigned n=0;n<20;++n)p.m_uSortOrder[n]=n;
            p.m_scoreGapOpen=-float(draw()%32+1)/4;p.m_scoreGapClose=-float(draw()%32+1)/4;
            for(unsigned n=0;n<4;++n){p.m_fcCounts[n]=float(draw()%16+1)/64;p.m_AAScores[n]=float(int(draw()%256)-128)/32;}
        }
        PWPath warm;
        NWSmall(a.data(),length,b.data(),length,warm);
        for(unsigned rep=0;rep<3;++rep){
            uint32_t checksum=0;auto start=Clock::now();
            for(unsigned iteration=0;iteration<30;++iteration){
                PWPath path;SCORE score=NWSmall(a.data(),length,b.data(),length,path);
                uint32_t bits;std::memcpy(&bits,&score,4);checksum=checksum*31+bits;
                for(unsigned e=0;e<path.GetEdgeCount();++e){const auto &edge=path.GetEdge(e);checksum=checksum*31+edge.cType;checksum=checksum*31+edge.uPrefixLengthA;checksum=checksum*31+edge.uPrefixLengthB;}
            }
            std::printf("KERNEL nw_%u %u %.6f %u\n",length,rep,milliseconds(start),checksum);
        }
    }
}
