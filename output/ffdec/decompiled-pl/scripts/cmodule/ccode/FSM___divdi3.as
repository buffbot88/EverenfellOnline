package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM___divdi3 extends Machine
   {
      
      public function FSM___divdi3()
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
         var _loc6_:int = 0;
         var _loc7_:int = 0;
         var _loc8_:int = 0;
         var _loc9_:int = 0;
         cmodule.ccode.mstate.esp -= 4;
         si32(cmodule.ccode.mstate.ebp,cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.ebp = cmodule.ccode.mstate.esp;
         cmodule.ccode.mstate.esp -= 0;
         _loc1_ = 0;
         _loc2_ = li32(cmodule.ccode.mstate.ebp + 12);
         _loc3_ = li32(cmodule.ccode.mstate.ebp + 20);
         _loc4_ = li32(cmodule.ccode.mstate.ebp + 8);
         _loc5_ = _loc2_ >> 31;
         _loc6_ = li32(cmodule.ccode.mstate.ebp + 16);
         _loc7_ = _loc3_ >> 31;
         _loc4_ = int(cmodule.ccode.__addc(_loc4_,_loc5_));
         _loc8_ = int(cmodule.ccode.__adde(_loc2_,_loc5_));
         _loc6_ = int(cmodule.ccode.__addc(_loc6_,_loc7_));
         _loc9_ = int(cmodule.ccode.__adde(_loc3_,_loc7_));
         cmodule.ccode.mstate.esp -= 20;
         _loc9_ ^= _loc7_;
         _loc6_ ^= _loc7_;
         _loc7_ = _loc8_ ^ _loc5_;
         _loc4_ ^= _loc5_;
         si32(_loc4_,cmodule.ccode.mstate.esp);
         si32(_loc7_,cmodule.ccode.mstate.esp + 4);
         si32(_loc6_,cmodule.ccode.mstate.esp + 8);
         si32(_loc9_,cmodule.ccode.mstate.esp + 12);
         si32(_loc1_,cmodule.ccode.mstate.esp + 16);
         cmodule.ccode.mstate.esp -= 4;
         FSM___qdivrem.start();
         _loc1_ = int(cmodule.ccode.mstate.eax);
         _loc4_ = int(cmodule.ccode.mstate.edx);
         cmodule.ccode.mstate.esp += 20;
         _loc2_ >>>= 31;
         _loc3_ >>>= 31;
         if(_loc2_ != _loc3_)
         {
            _loc2_ = 0;
            _loc1_ = int(cmodule.ccode.__subc(_loc2_,_loc1_));
            _loc4_ = int(cmodule.ccode.__sube(_loc2_,_loc4_));
         }
         cmodule.ccode.mstate.edx = _loc4_;
         cmodule.ccode.mstate.eax = _loc1_;
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

