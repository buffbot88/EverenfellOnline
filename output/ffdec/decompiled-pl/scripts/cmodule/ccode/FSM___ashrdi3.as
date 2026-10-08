package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM___ashrdi3 extends Machine
   {
      
      public function FSM___ashrdi3()
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
         _loc1_ = li32(cmodule.ccode.mstate.ebp + 16);
         _loc2_ = li32(cmodule.ccode.mstate.ebp + 20);
         _loc3_ = li32(cmodule.ccode.mstate.ebp + 8);
         _loc4_ = li32(cmodule.ccode.mstate.ebp + 12);
         _loc5_ = uint(_loc1_) < uint(32) ? 1 : 0;
         while(true)
         {
            _loc6_ = _loc2_ == 0 ? 1 : 0;
            _loc5_ = _loc6_ != 0 ? _loc5_ : 0;
            if(_loc5_ == 0)
            {
               _loc3_ = 0;
               _loc5_ = _loc4_ >> 31;
               _loc6_ = _loc2_ != 0 ? 1 : 0;
               _loc7_ = uint(_loc1_) > uint(63) ? 1 : 0;
               _loc2_ = _loc2_ == 0 ? 1 : 0;
               _loc8_ = _loc3_;
               _loc9_ = _loc5_;
               _loc2_ = _loc2_ != 0 ? _loc7_ : _loc6_;
               if(_loc2_ != 0)
               {
                  _loc1_ = _loc5_ | _loc3_;
                  _loc2_ = _loc8_ | _loc9_;
                  cmodule.ccode.mstate.edx = _loc1_;
                  cmodule.ccode.mstate.eax = _loc2_;
                  break;
               }
               _loc3_ = _loc1_ + -32;
               _loc3_ = _loc4_ >> _loc3_;
               _loc3_ |= _loc8_;
               cmodule.ccode.mstate.edx = _loc5_;
            }
            else
            {
               _loc2_ = _loc1_ | _loc2_;
               if(_loc2_ != 0)
               {
                  _loc2_ = 32 - _loc1_;
                  _loc2_ = _loc4_ << _loc2_;
                  _loc3_ >>>= _loc1_;
                  _loc4_ >>= _loc1_;
                  _loc3_ = _loc2_ | _loc3_;
               }
               cmodule.ccode.mstate.edx = _loc4_;
            }
            cmodule.ccode.mstate.eax = _loc3_;
            break;
         }
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

