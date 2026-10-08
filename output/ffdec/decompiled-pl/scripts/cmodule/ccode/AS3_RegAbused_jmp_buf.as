package cmodule.ccode
{
   function AS3_RegAbused_jmp_buf(param1:int) : void
   {
      cmodule.ccode.log(4,"regAbused: " + param1);
      cmodule.ccode.log(1,"Can\'t RegAbused -- abuse support disabled");
   }
}

