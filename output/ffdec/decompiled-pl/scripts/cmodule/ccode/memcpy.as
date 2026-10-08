package cmodule.ccode
{
   public function memcpy(param1:int, param2:int, param3:int) : int
   {
      if(param3)
      {
         cmodule.ccode.gstate.ds.position = param1;
         cmodule.ccode.gstate.ds.writeBytes(cmodule.ccode.gstate.ds,param2,param3);
      }
      return param1;
   }
}

