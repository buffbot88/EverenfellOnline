package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM___subdi3 extends Machine
   {
      
      public function FSM___subdi3()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:int = 0;
         var _loc2_:int = 0;
         var _loc3_:int = 0;
         var _loc4_:int = 0;
         cmodule.ccode.mstate.esp -= 4;
         si32(cmodule.ccode.mstate.ebp,cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.ebp = cmodule.ccode.mstate.esp;
         cmodule.ccode.mstate.esp -= 0;
         _loc1_ = li32(cmodule.ccode.mstate.ebp + 8);
         _loc2_ = li32(cmodule.ccode.mstate.ebp + 16);
         _loc2_ = _loc1_ - _loc2_;
         _loc1_ = uint(_loc2_) > uint(_loc1_) ? 1 : 0;
         _loc3_ = li32(cmodule.ccode.mstate.ebp + 12);
         _loc4_ = li32(cmodule.ccode.mstate.ebp + 20);
         _loc3_ = int(cmodule.ccode.__subc(_loc3_,_loc4_));
         _loc1_ &= 1;
         _loc1_ = int(cmodule.ccode.__subc(_loc3_,_loc1_));
         cmodule.ccode.mstate.edx = _loc1_;
         cmodule.ccode.mstate.eax = _loc2_;
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

