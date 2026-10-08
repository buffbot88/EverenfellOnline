package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM___floatunsdidf extends Machine
   {
      
      public function FSM___floatunsdidf()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:int = 0;
         var _loc2_:int = 0;
         var _loc3_:Number = NaN;
         var _loc4_:Number = NaN;
         cmodule.ccode.mstate.esp -= 4;
         si32(cmodule.ccode.mstate.ebp,cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.ebp = cmodule.ccode.mstate.esp;
         cmodule.ccode.mstate.esp -= 0;
         _loc1_ = li32(cmodule.ccode.mstate.ebp + 12);
         _loc2_ = li32(cmodule.ccode.mstate.ebp + 8);
         _loc3_ = Number(uint(_loc1_));
         _loc4_ = Number(uint(_loc2_));
         _loc3_ *= 4294970000;
         _loc3_ = _loc4_ + _loc3_;
         cmodule.ccode.mstate.st0 = _loc3_;
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

