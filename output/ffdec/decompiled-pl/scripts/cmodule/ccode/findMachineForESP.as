package cmodule.ccode
{
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   function findMachineForESP(param1:int) : Machine
   {
      var _loc2_:Object = null;
      for(_loc2_ in cmodule.ccode.gsetjmpMachine2ESPMap)
      {
         if(cmodule.ccode.gsetjmpMachine2ESPMap[_loc2_] == param1)
         {
            return Machine(_loc2_);
         }
      }
      return null;
   }
}

