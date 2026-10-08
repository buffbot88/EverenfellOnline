package cmodule.ccode
{
   public function vgl_unlock() : void
   {
      if(Boolean(cmodule.ccode.gvglbmd) && Boolean(cmodule.ccode.gvglpixels))
      {
         cmodule.ccode.gstate.ds.position = cmodule.ccode.gvglpixels;
         cmodule.ccode.gvglbmd.setPixels(cmodule.ccode.gvglbmd.rect,cmodule.ccode.gstate.ds);
      }
   }
}

