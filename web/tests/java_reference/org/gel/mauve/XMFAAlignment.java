package org.gel.mauve;
import java.nio.charset.StandardCharsets;
// Fixture adapter only. SimilarityIndex and ZoomHistogram are compiled unchanged.
public class XMFAAlignment {
  final String[] rows;
  XMFAAlignment(String[] rows) { this.rows=rows; }
  public byte[][] getRange(Genome g, long left, long right) {
    int first=0,last=0,count=0;
    for(int i=0;i<rows[g.index].length();i++) if(rows[g.index].charAt(i)!='-') {
      count++; if(count==left) first=i; if(count==right) {last=i;break;}
    }
    byte[][] result=new byte[rows.length][];
    for(int i=0;i<rows.length;i++) result[i]=rows[i].substring(first,last+1).getBytes(StandardCharsets.US_ASCII);
    return result;
  }
}
