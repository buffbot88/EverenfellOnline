package cmodule.ccode
{
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   public function modPostStaticInit() : void
   {
      var _loc1_:int = 0;
      if(cmodule.ccode.gpostStaticInits)
      {
         _loc1_ = 0;
         while(_loc1_ < cmodule.ccode.gpostStaticInits.length)
         {
            cmodule.ccode.gpostStaticInits[_loc1_]();
            _loc1_++;
         }
      }
   }
}

