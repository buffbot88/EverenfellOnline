package cmodule.ccode
{
   public function __adde(param1:uint, param2:uint) : uint
   {
      var _loc3_:uint = param1 + param2 + cmodule.ccode.gstate.cf;
      cmodule.ccode.gstate.cf = uint(_loc3_ < param1);
      return _loc3_;
   }
}

