package org.gel.mauve.backbone;
import org.gel.mauve.Genome;
public class Backbone {
  final boolean[] seqs;
  public Backbone(boolean[] seqs) { this.seqs=seqs; }
  public long getLeftEnd(Genome g) {return 1;}
  public long getRightEnd(Genome g) {return g.getLength();}
  public boolean[] getSeqs() {return seqs;}
}
