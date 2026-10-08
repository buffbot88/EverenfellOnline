package cmodule.ccode
{
   public function _sbrk(param1:int) : int
   {
      var _loc2_:int = int(cmodule.ccode.gstate.ds.length);
      var _loc3_:int = _loc2_ + param1;
      cmodule.ccode.gstate.ds.length = _loc3_;
      return _loc2_;
   }
}

