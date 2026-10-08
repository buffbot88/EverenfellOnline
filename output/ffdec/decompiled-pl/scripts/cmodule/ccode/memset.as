package cmodule.ccode
{
   public function memset(param1:int, param2:int, param3:int) : int
   {
      var _loc4_:int = param2 | param2 << 8 | param2 << 16 | param2 << 24;
      cmodule.ccode.gstate.ds.position = param1;
      while(param3 >= 4)
      {
         cmodule.ccode.gstate.ds.writeUnsignedInt(_loc4_);
         param3 -= 4;
      }
      while(param3--)
      {
         cmodule.ccode.gstate.ds.writeByte(param2);
      }
      return param1;
   }
}

