package cmodule.ccode
{
   import flash.utils.ByteArray;
   
   function AS3_Ram() : ByteArray
   {
      return cmodule.ccode.gstate.ds;
   }
}

