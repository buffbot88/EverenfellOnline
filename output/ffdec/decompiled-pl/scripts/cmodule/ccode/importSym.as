package cmodule.ccode
{
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   public function importSym(param1:String) : int
   {
      var s:String = param1;
      var res:int = int(cmodule.ccode.gstate.syms[s]);
      if(!res)
      {
         cmodule.ccode.log(3,"Undefined sym: " + s);
         return cmodule.ccode.exportSym(s,cmodule.ccode.regFunc(function():*
         {
            throw "Undefined sym: " + s;
         }));
      }
      return res;
   }
}

