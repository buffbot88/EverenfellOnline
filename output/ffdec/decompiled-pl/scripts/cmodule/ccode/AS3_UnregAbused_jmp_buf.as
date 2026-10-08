package cmodule.ccode
{
   function AS3_UnregAbused_jmp_buf(param1:int) : void
   {
      cmodule.ccode.log(4,"unregAbused: " + param1);
      cmodule.ccode.log(1,"Can\'t UnregAbused -- abuse support disabled");
   }
}

