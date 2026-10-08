package cmodule.ccode
{
   import avm2.intrinsics.memory.lf64;
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.sf64;
   import avm2.intrinsics.memory.si32;
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   public final class FSM___fixdfdi extends Machine
   {
      
      public function FSM___fixdfdi()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:int = 0;
         var _loc2_:int = 0;
         var _loc3_:int = 0;
         var _loc4_:Number = NaN;
         var _loc5_:Number = NaN;
         cmodule.ccode.mstate.esp -= 4;
         si32(cmodule.ccode.mstate.ebp,cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.ebp = cmodule.ccode.mstate.esp;
         cmodule.ccode.mstate.esp -= 0;
         _loc4_ = 0;
         _loc5_ = lf64(cmodule.ccode.mstate.ebp + 8);
         if(_loc5_ < _loc4_)
         {
            _loc4_ = -9223370000000000000;
            if(_loc5_ <= _loc4_)
            {
               _loc1_ = -2147483648;
               _loc2_ = 0;
            }
            else
            {
               _loc1_ = 0;
               cmodule.ccode.mstate.esp -= 8;
               _loc5_ = -_loc5_;
               sf64(_loc5_,cmodule.ccode.mstate.esp);
               cmodule.ccode.mstate.esp -= 4;
               cmodule.ccode.mstate.funcs[cmodule.ccode.___fixunsdfdi]();
               _loc2_ = int(cmodule.ccode.mstate.eax);
               _loc3_ = int(cmodule.ccode.mstate.edx);
               cmodule.ccode.mstate.esp += 8;
               _loc2_ = int(cmodule.ccode.__subc(_loc1_,_loc2_));
               _loc1_ = int(cmodule.ccode.__sube(_loc1_,_loc3_));
            }
            addr0175:
            cmodule.ccode.mstate.edx = _loc1_;
            cmodule.ccode.mstate.eax = _loc2_;
         }
         else
         {
            _loc4_ = 9223370000000000000;
            if(_loc5_ >= _loc4_)
            {
               _loc1_ = 2147483647;
               _loc2_ = -1;
               §§goto(addr0175);
            }
            else
            {
               cmodule.ccode.mstate.esp -= 8;
               sf64(_loc5_,cmodule.ccode.mstate.esp);
               cmodule.ccode.mstate.esp -= 4;
               cmodule.ccode.mstate.funcs[cmodule.ccode.___fixunsdfdi]();
               _loc1_ = int(cmodule.ccode.mstate.eax);
               _loc2_ = int(cmodule.ccode.mstate.edx);
               cmodule.ccode.mstate.esp += 8;
               cmodule.ccode.mstate.edx = _loc2_;
               cmodule.ccode.mstate.eax = _loc1_;
            }
         }
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

