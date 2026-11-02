package org.gel.mauve.backbone;
import org.gel.mauve.Genome;
public class BackboneList {
  final Backbone bb;
  public BackboneList(boolean[] seqs) { bb=new Backbone(seqs); }
  public Backbone getBackbone(Genome g,long p) {return bb.getSeqs()[g.getSourceIndex()] ? bb : null;}
  public Backbone getNextBackbone(Genome g,long p) {return null;}
}
