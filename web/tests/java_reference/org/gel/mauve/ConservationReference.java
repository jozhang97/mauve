package org.gel.mauve;
import java.nio.file.*;
import java.util.*;
import org.gel.mauve.backbone.*;
public class ConservationReference {
  public static void main(String[] args) throws Exception {
    String[] rows=Files.readAllLines(Path.of(args[0])).toArray(new String[0]);
    int gid=Integer.parseInt(args[1]);
    Genome genome=new Genome(gid, rows[gid].replace("-", "").length());
    BackboneList bb=null;
    if(args.length>2) { boolean[] seqs=new boolean[rows.length]; for(String s:args[2].split(",")) seqs[Integer.parseInt(s)]=true; bb=new BackboneList(seqs); }
    SimilarityIndex index=new SimilarityIndex(genome,new XMFAAlignment(rows),bb);
    System.out.print("{\"base\":[");
    for(int i=0;i<index.getLevelSize(0);i++) { if(i>0)System.out.print(",");System.out.print(index.getSimilarity(0,i)); }
    System.out.print("],\"queries\":["); boolean comma=false;
    long[][] ranges={{1,1},{1,10},{3,17},{0,genome.length},{7,Math.min(83,genome.length)},{1,Math.min(1500,genome.length)},{Math.max(1,genome.length-15),genome.length}};
    for(long[] r:ranges) {if(comma)System.out.print(",");comma=true; System.out.print("["+r[0]+","+r[1]+","+index.getValueForRange(r[0],r[1])+","+index.getValueForRange(r[0],r[1],-1)+","+index.getValueForRange(r[0],r[1],1)+"]");}
    System.out.println("]}");
  }
}
