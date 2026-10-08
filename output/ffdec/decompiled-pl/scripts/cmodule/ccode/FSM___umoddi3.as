package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM___umoddi3 extends Machine
   {
      
      public function FSM___umoddi3()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:int = 0;
         var _loc2_:int = 0;
         var _loc3_:int = 0;
         var _loc4_:int = 0;
         var _loc5_:int = 0;
         cmodule.ccode.mstate.esp -= 4;
         si32(cmodule.ccode.mstate.ebp,cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.ebp = cmodule.ccode.mstate.esp;
         cmodule.ccode.mstate.esp -= 8;
         _loc1_ = cmodule.ccode.mstate.ebp + -8;
         cmodule.ccode.mstate.esp -= 20;
         _loc2_ = li32(cmodule.ccode.mstate.ebp + 8);
         _loc3_ = li32(cmodule.ccode.mstate.ebp + 12);
         _loc4_ = li32(cmodule.ccode.mstate.ebp + 16);
         _loc5_ = li32(cmodule.ccode.mstate.ebp + 20);
         si32(_loc2_,cmodule.ccode.mstate.esp);
         si32(_loc3_,cmodule.ccode.mstate.esp + 4);
         si32(_loc4_,cmodule.ccode.mstate.esp + 8);
         si32(_loc5_,cmodule.ccode.mstate.esp + 12);
         si32(_loc1_,cmodule.ccode.mstate.esp + 16);
         cmodule.ccode.mstate.esp -= 4;
         FSM___qdivrem.start();
         _loc1_ = int(cmodule.ccode.mstate.eax);
         _loc1_ = int(cmodule.ccode.mstate.edx);
         cmodule.ccode.mstate.esp += 20;
         _loc1_ = li32(cmodule.ccode.mstate.ebp + -8);
         _loc2_ = li32(cmodule.ccode.mstate.ebp + -4);
         cmodule.ccode.mstate.edx = _loc2_;
         cmodule.ccode.mstate.eax = _loc1_;
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

