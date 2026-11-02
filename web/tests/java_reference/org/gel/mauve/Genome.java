package org.gel.mauve;
public class Genome {
  final int index; final long length;
  Genome(int index, long length) { this.index=index; this.length=length; }
  public int getSourceIndex() { return index; }
  public long getLength() { return length; }
}
