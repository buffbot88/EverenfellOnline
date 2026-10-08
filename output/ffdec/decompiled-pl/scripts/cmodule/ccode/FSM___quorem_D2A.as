package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.si32;
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   public final class FSM___quorem_D2A extends Machine
   {
      
      public function FSM___quorem_D2A()
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
         var _loc13_:int = 0;
         var _loc14_:int = 0;
         var _loc15_:int = 0;
         var _loc16_:int = 0;
         var _loc17_:int = 0;
         var _loc18_:int = 0;
         var _loc19_:int = 0;
         var _loc20_:int = 0;
         var _loc21_:int = 0;
         var _loc22_:int = 0;
         var _loc23_:int = 0;
         var _loc24_:int = 0;
         cmodule.ccode.mstate.esp -= 4;
         si32(cmodule.ccode.mstate.ebp,cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.ebp = cmodule.ccode.mstate.esp;
         cmodule.ccode.mstate.esp -= 0;
         _loc1_ = li32(cmodule.ccode.mstate.ebp + 8);
         _loc2_ = li32(cmodule.ccode.mstate.ebp + 12);
         _loc3_ = li32(_loc2_ + 16);
         _loc4_ = li32(_loc1_ + 16);
         _loc5_ = _loc1_ + 16;
         _loc6_ = _loc2_ + 16;
         _loc7_ = _loc2_;
         _loc8_ = _loc1_;
         if(_loc4_ < _loc3_)
         {
            _loc1_ = 0;
            addr00e8:
            cmodule.ccode.mstate.eax = _loc1_;
         }
         else
         {
            _loc9_ = _loc3_ + -1;
            _loc10_ = _loc9_ << 2;
            _loc11_ = _loc2_ + _loc10_;
            _loc11_ = li32(_loc11_ + 20);
            _loc10_ = _loc1_ + _loc10_;
            _loc12_ = li32(_loc10_ + 20);
            _loc11_ += 1;
            _loc10_ += 20;
            while(true)
            {
               _loc11_ = uint(_loc12_) / uint(_loc11_);
               if(_loc11_ != 0)
               {
                  _loc12_ = 20;
                  _loc14_ = _loc13_ = 0;
                  _loc15_ = _loc13_;
                  _loc16_ = _loc13_;
                  _loc17_ = _loc11_;
                  _loc18_ = _loc15_;
                  _loc19_ = _loc14_;
                  while(true)
                  {
                     _loc20_ = 0;
                     _loc21_ = _loc7_ + _loc12_;
                     cmodule.ccode.mstate.esp -= 16;
                     _loc21_ = li32(_loc21_);
                     si32(_loc21_,cmodule.ccode.mstate.esp);
                     si32(_loc20_,cmodule.ccode.mstate.esp + 4);
                     si32(_loc17_,cmodule.ccode.mstate.esp + 8);
                     si32(_loc13_,cmodule.ccode.mstate.esp + 12);
                     cmodule.ccode.mstate.esp -= 4;
                     cmodule.ccode.mstate.funcs[cmodule.ccode.___muldi3]();
                     _loc21_ = int(cmodule.ccode.mstate.eax);
                     _loc22_ = int(cmodule.ccode.mstate.edx);
                     _loc23_ = _loc8_ + _loc12_;
                     _loc24_ = li32(_loc23_);
                     _loc15_ = int(cmodule.ccode.__addc(_loc21_,_loc15_));
                     _loc14_ = int(cmodule.ccode.__adde(_loc22_,_loc14_));
                     _loc15_ = int(cmodule.ccode.__subc(_loc24_,_loc15_));
                     _loc21_ = int(cmodule.ccode.__sube(_loc20_,_loc20_));
                     _loc15_ = int(cmodule.ccode.__subc(_loc15_,_loc18_));
                     _loc18_ = int(cmodule.ccode.__sube(_loc21_,_loc19_));
                     si32(_loc15_,_loc23_);
                     _loc15_ = _loc18_ & 1;
                     _loc12_ += 4;
                     _loc16_ += 1;
                     cmodule.ccode.mstate.esp += 16;
                     _loc19_ = _loc20_;
                     if(_loc16_ > _loc9_)
                     {
                        break;
                     }
                     _loc18_ = _loc15_;
                     _loc15_ = _loc14_;
                     _loc14_ = _loc20_;
                  }
                  _loc10_ = li32(_loc10_);
                  if(_loc10_ == 0)
                  {
                     _loc4_ = _loc3_ + -2;
                     if(_loc4_ <= 0)
                     {
                        _loc3_ = _loc9_;
                     }
                     else
                     {
                        _loc10_ = 0;
                        _loc12_ = _loc3_ << 2;
                        _loc12_ = _loc8_ + _loc12_;
                        _loc12_ = _loc12_ + 12;
                        _loc3_ += -1;
                        while(true)
                        {
                           _loc13_ = _loc12_;
                           _loc12_ = _loc3_;
                           _loc3_ = _loc10_;
                           _loc10_ = li32(_loc13_);
                           if(_loc10_ != 0)
                           {
                              _loc3_ = _loc12_;
                              break;
                           }
                           _loc10_ = _loc13_ + -4;
                           _loc13_ = _loc12_ + -1;
                           _loc14_ = _loc3_ + 1;
                           _loc3_ ^= -1;
                           _loc3_ = _loc4_ + _loc3_;
                           if(_loc3_ <= 0)
                           {
                              _loc3_ = _loc13_;
                              break;
                           }
                           _loc12_ = _loc10_;
                           _loc3_ = _loc13_;
                           _loc10_ = _loc14_;
                        }
                     }
                     _loc4_ = _loc3_;
                     si32(_loc4_,_loc5_);
                     _loc3_ = _loc4_;
                     break;
                  }
               }
               _loc3_ = _loc4_;
               _loc4_ = _loc9_;
               break;
            }
            _loc6_ = li32(_loc6_);
            _loc10_ = _loc3_ - _loc6_;
            if(_loc3_ != _loc6_)
            {
               _loc2_ = _loc10_;
            }
            else
            {
               _loc3_ = 0;
               while(true)
               {
                  _loc10_ = _loc3_ ^ -1;
                  _loc10_ = _loc6_ + _loc10_;
                  _loc12_ = _loc10_ << 2;
                  _loc13_ = _loc1_ + _loc12_;
                  _loc12_ = _loc2_ + _loc12_;
                  _loc13_ = li32(_loc13_ + 20);
                  _loc12_ = li32(_loc12_ + 20);
                  if(_loc13_ != _loc12_)
                  {
                     _loc2_ = uint(_loc13_) < uint(_loc12_) ? -1 : 1;
                     break;
                  }
                  _loc3_ += 1;
                  if(_loc10_ <= 0)
                  {
                     _loc2_ = 0;
                     break;
                  }
               }
            }
            if(_loc2_ <= -1)
            {
               _loc1_ = _loc11_;
               addr00e7:
               §§goto(addr00e8);
            }
            else
            {
               _loc2_ = 0;
               _loc3_ = 20;
               _loc6_ = _loc11_ + 1;
               _loc10_ = _loc2_;
               _loc12_ = _loc11_ = _loc2_;
               _loc13_ = _loc10_;
               while(true)
               {
                  _loc14_ = 0;
                  _loc15_ = _loc7_ + _loc3_;
                  _loc15_ = li32(_loc15_);
                  _loc16_ = _loc8_ + _loc3_;
                  _loc17_ = li32(_loc16_);
                  _loc11_ = int(cmodule.ccode.__addc(_loc15_,_loc11_));
                  _loc10_ = int(cmodule.ccode.__adde(_loc10_,_loc14_));
                  _loc11_ = int(cmodule.ccode.__subc(_loc17_,_loc11_));
                  _loc15_ = int(cmodule.ccode.__sube(_loc14_,_loc14_));
                  _loc11_ = int(cmodule.ccode.__subc(_loc11_,_loc12_));
                  _loc12_ = int(cmodule.ccode.__sube(_loc15_,_loc13_));
                  si32(_loc11_,_loc16_);
                  _loc11_ = _loc12_ & 1;
                  _loc3_ += 4;
                  _loc2_ += 1;
                  _loc13_ = _loc14_;
                  if(_loc2_ > _loc9_)
                  {
                     break;
                  }
                  _loc12_ = _loc11_;
                  _loc11_ = _loc10_;
                  _loc10_ = _loc14_;
               }
               _loc2_ = _loc4_ << 2;
               _loc2_ = _loc1_ + _loc2_;
               _loc2_ = li32(_loc2_ + 20);
               if(_loc2_ != 0)
               {
                  _loc1_ = _loc6_;
                  §§goto(addr00e7);
               }
               else
               {
                  _loc2_ = 0;
                  while(true)
                  {
                     _loc3_ = _loc2_ ^ -1;
                     _loc3_ = _loc4_ + _loc3_;
                     if(_loc3_ < 1)
                     {
                        break;
                     }
                     _loc3_ <<= 2;
                     _loc3_ = _loc1_ + _loc3_;
                     _loc3_ = li32(_loc3_ + 20);
                     if(_loc3_ != 0)
                     {
                        break;
                     }
                     _loc2_ += 1;
                  }
                  _loc1_ = _loc4_ - _loc2_;
                  si32(_loc1_,_loc5_);
                  cmodule.ccode.mstate.eax = _loc6_;
               }
            }
         }
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

