package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.li8;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM_strstr extends Machine
   {
      
      public function FSM_strstr()
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
         var _loc10_:int = 0;
         var _loc11_:int = 0;
         var _loc12_:int = 0;
         cmodule.ccode.mstate.esp -= 4;
         si32(cmodule.ccode.mstate.ebp,cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.ebp = cmodule.ccode.mstate.esp;
         cmodule.ccode.mstate.esp -= 0;
         _loc1_ = li32(cmodule.ccode.mstate.ebp + 12);
         _loc2_ = li8(_loc1_);
         _loc3_ = li32(cmodule.ccode.mstate.ebp + 8);
         _loc4_ = _loc1_ + 1;
         _loc5_ = _loc3_;
         if(_loc2_ == 0)
         {
            _loc1_ = _loc3_;
            addr00a3:
            cmodule.ccode.mstate.eax = _loc1_;
         }
         else
         {
            _loc3_ = li8(_loc4_);
            if(_loc3_ != 0)
            {
               _loc3_ = _loc1_;
               do
               {
                  _loc6_ = li8(_loc3_ + 2);
                  _loc3_ += 1;
               }
               while(_loc6_ != 0);
               _loc3_ += 1;
            }
            else
            {
               _loc3_ = _loc4_;
            }
            _loc6_ = _loc4_;
            _loc7_ = _loc3_;
            while(true)
            {
               _loc8_ = li8(_loc5_);
               _loc9_ = _loc5_;
               if(_loc8_ != 0)
               {
                  _loc10_ = _loc2_ & 0xFF;
                  _loc8_ &= 255;
                  if(_loc8_ == _loc10_)
                  {
                     if(_loc3_ == _loc4_)
                     {
                        cmodule.ccode.mstate.eax = _loc9_;
                        break;
                     }
                     _loc8_ = 1;
                     _loc10_ = _loc7_ - _loc6_;
                     while(true)
                     {
                        _loc11_ = _loc1_ + _loc8_;
                        _loc12_ = _loc5_ + _loc8_;
                        _loc12_ = li8(_loc12_);
                        _loc11_ = li8(_loc11_);
                        if(_loc12_ != _loc11_)
                        {
                           break;
                        }
                        _loc11_ = _loc10_ + -1;
                        _loc8_ += 1;
                        _loc12_ &= 255;
                        if(_loc12_ != 0)
                        {
                           if(_loc10_ != 1)
                           {
                              continue;
                           }
                        }
                        _loc10_ = _loc11_;
                     }
                  }
                  continue;
               }
               _loc1_ = 0;
               §§goto(addr00a3);
               _loc5_ += 1;
            }
         }
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

