package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM___lo0bits_D2A extends Machine
   {
      
      public function FSM___lo0bits_D2A()
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
         cmodule.ccode.mstate.esp -= 0;
         _loc1_ = li32(cmodule.ccode.mstate.ebp + 8);
         _loc2_ = li32(_loc1_);
         _loc3_ = _loc2_ & 7;
         while(true)
         {
            if(_loc3_ != 0)
            {
               _loc3_ = _loc2_ & 1;
               if(_loc3_ == 0)
               {
                  _loc3_ = _loc2_ & 2;
                  if(_loc3_ != 0)
                  {
                     _loc3_ = 1;
                     _loc2_ >>>= 1;
                  }
                  else
                  {
                     _loc3_ = 2;
                     _loc2_ >>>= 2;
                  }
                  addr0161:
                  si32(_loc2_,_loc1_);
                  cmodule.ccode.mstate.eax = _loc3_;
                  break;
               }
               _loc1_ = 0;
            }
            else
            {
               _loc3_ = _loc2_ & 0xFFFF;
               _loc3_ = _loc3_ == 0 ? 16 : 0;
               _loc2_ >>>= _loc3_;
               _loc4_ = _loc2_ & 0xFF;
               _loc4_ = _loc4_ == 0 ? 8 : 0;
               _loc2_ >>>= _loc4_;
               _loc5_ = _loc2_ & 0x0F;
               _loc5_ = _loc5_ == 0 ? 4 : 0;
               _loc2_ >>>= _loc5_;
               _loc3_ = _loc4_ | _loc3_;
               _loc4_ = _loc2_ & 3;
               _loc4_ = _loc4_ == 0 ? 2 : 0;
               _loc3_ |= _loc5_;
               _loc2_ >>>= _loc4_;
               _loc3_ |= _loc4_;
               _loc4_ = _loc2_ & 1;
               if(_loc4_ == 0)
               {
                  _loc4_ = _loc2_ >>> 1;
                  _loc3_ += 1;
                  if(uint(_loc2_) < uint(2))
                  {
                     _loc1_ = 32;
                     addr0176:
                     cmodule.ccode.mstate.eax = _loc1_;
                     break;
                  }
                  _loc2_ = _loc4_;
               }
               §§goto(addr0161);
            }
            §§goto(addr0176);
         }
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

