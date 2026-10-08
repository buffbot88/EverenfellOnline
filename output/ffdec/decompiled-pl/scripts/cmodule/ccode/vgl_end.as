package cmodule.ccode
{
   public function vgl_end(param1:int) : int
   {
      var _loc2_:int = 0;
      _loc2_ = cmodule.ccode.gvglpixels;
      cmodule.ccode.gvglpixels = 0;
      return _loc2_;
   }
}

