package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.li8;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM_malloc_pages extends Machine
   {
      
      public function FSM_malloc_pages()
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
         cmodule.ccode.mstate.esp -= 4;
         si32(cmodule.ccode.mstate.ebp,cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.ebp = cmodule.ccode.mstate.esp;
         cmodule.ccode.mstate.esp -= 0;
         _loc1_ = li32(cmodule.ccode.mstate.ebp + 8);
         _loc1_ += 4095;
         _loc2_ = li32(cmodule.ccode._free_list);
         _loc3_ = _loc1_ & -4096;
         loop2:
         while(true)
         {
            if(_loc2_ != 0)
            {
               _loc1_ = _loc2_;
               while(true)
               {
                  _loc2_ = li32(_loc1_ + 16);
                  _loc4_ = _loc1_ + 16;
                  if(uint(_loc2_) >= uint(_loc3_))
                  {
                     _loc5_ = li32(_loc1_ + 8);
                     _loc6_ = _loc1_ + 8;
                     if(_loc2_ == _loc3_)
                     {
                        _loc2_ = li32(_loc1_);
                        _loc4_ = _loc1_;
                        if(_loc2_ != 0)
                        {
                           _loc6_ = li32(_loc1_ + 4);
                           si32(_loc6_,_loc2_ + 4);
                        }
                        _loc2_ = li32(_loc1_ + 4);
                        _loc4_ = li32(_loc4_);
                        si32(_loc4_,_loc2_);
                        _loc2_ = _loc3_ >>> 12;
                        if(_loc5_ != 0)
                        {
                           _loc4_ = _loc5_;
                           break;
                        }
                        break loop2;
                     }
                     _loc1_ = _loc5_ + _loc3_;
                     si32(_loc1_,_loc6_);
                     _loc1_ = _loc2_ - _loc3_;
                     si32(_loc1_,_loc4_);
                     _loc2_ = _loc3_ >>> 12;
                     if(_loc5_ != 0)
                     {
                        _loc1_ = 0;
                        _loc4_ = _loc5_;
                        break;
                     }
                     _loc1_ = 0;
                     break loop2;
                  }
                  _loc1_ = li32(_loc1_);
                  if(_loc1_ != 0)
                  {
                     continue;
                  }
               }
               §§goto(addr0301);
            }
            _loc1_ = 0;
            _loc2_ = _loc3_ >>> 12;
            break;
         }
         _loc4_ = _loc1_;
         _loc5_ = _loc2_;
         _loc1_ = 0;
         _loc1_ = cmodule.ccode._sbrk(_loc1_);
         _loc1_ += 4095;
         _loc6_ = _loc1_ & -4096;
         _loc1_ = _loc6_ + _loc3_;
         while(true)
         {
            if(uint(_loc1_) >= uint(_loc6_))
            {
               _loc2_ = _loc1_;
               _loc2_ = cmodule.ccode._brk(_loc2_);
               if(_loc2_ == 0)
               {
                  _loc2_ = _loc1_ >>> 12;
                  _loc7_ = li32(cmodule.ccode._malloc_origo);
                  _loc2_ += -1;
                  _loc7_ = _loc2_ - _loc7_;
                  si32(_loc7_,cmodule.ccode._last_index);
                  si32(_loc1_,cmodule.ccode._malloc_brk);
                  _loc1_ = li32(cmodule.ccode._malloc_ninfo);
                  _loc2_ = _loc7_ + 1;
                  if(uint(_loc2_) < uint(_loc1_))
                  {
                     _loc1_ = _loc4_;
                     _loc2_ = _loc5_;
                     _loc4_ = _loc6_;
                     break;
                  }
                  _loc1_ = cmodule.ccode.__2E_str8;
                  _loc2_ = 4;
                  _loc8_ = 0;
                  cmodule.ccode.log(_loc2_,cmodule.ccode.mstate.gworker.stringFromPtr(_loc1_));
                  _loc1_ = cmodule.ccode._sbrk(_loc8_);
                  _loc1_ &= 4095;
                  _loc1_ = 4096 - _loc1_;
                  _loc2_ = _loc7_ >>> 9;
                  _loc1_ &= 4095;
                  _loc2_ &= 1048575;
                  _loc2_ += 2;
                  _loc1_ = cmodule.ccode._sbrk(_loc1_);
                  _loc1_ = _loc2_ << 12;
                  _loc1_ = cmodule.ccode._sbrk(_loc1_);
                  _loc7_ = _loc1_;
                  if(_loc1_ != -1)
                  {
                     _loc8_ = cmodule.ccode.__2E_str311;
                     _loc9_ = li32(cmodule.ccode._malloc_ninfo);
                     _loc10_ = li32(cmodule.ccode._page_dir);
                     _loc9_ <<= 2;
                     _loc2_ <<= 10;
                     cmodule.ccode.memcpy(_loc1_,_loc10_,_loc9_);
                     _loc1_ = _loc2_ & 0x3FFFFC00;
                     si32(_loc1_,cmodule.ccode._malloc_ninfo);
                     si32(_loc7_,cmodule.ccode._page_dir);
                     _loc2_ = 4;
                     _loc1_ = _loc8_;
                     cmodule.ccode.log(_loc2_,cmodule.ccode.mstate.gworker.stringFromPtr(_loc1_));
                     _loc1_ = _loc4_;
                     _loc2_ = _loc5_;
                     _loc4_ = _loc6_;
                     break;
                  }
               }
            }
            _loc6_ = 0;
            _loc1_ = _loc4_;
            _loc2_ = _loc5_;
            _loc4_ = _loc6_;
            break;
         }
         addr0301:
         if(_loc4_ != 0)
         {
            _loc5_ = 2;
            _loc6_ = li32(cmodule.ccode._malloc_origo);
            _loc7_ = _loc4_ >>> 12;
            _loc8_ = _loc7_ - _loc6_;
            _loc9_ = li32(cmodule.ccode._page_dir);
            _loc8_ <<= 2;
            _loc8_ = _loc9_ + _loc8_;
            si32(_loc5_,_loc8_);
            if(uint(_loc2_) >= uint(2))
            {
               _loc5_ = 0;
               _loc6_ = _loc7_ - _loc6_;
               _loc6_ = _loc6_ << 2;
               _loc6_ = _loc6_ + _loc9_;
               _loc6_ = _loc6_ + 4;
               _loc2_ += -1;
               do
               {
                  _loc7_ = 3;
                  si32(_loc7_,_loc6_);
                  _loc6_ += 4;
               }
               while(_loc5_ += 1, _loc5_ != _loc2_);
            }
            _loc2_ = li8(cmodule.ccode._malloc_junk_2E_b);
            _loc2_ ^= 1;
            _loc2_ &= 1;
            if(_loc2_ == 0)
            {
               _loc2_ = -48;
               _loc5_ = _loc4_;
               cmodule.ccode.memset(_loc5_,_loc2_,_loc3_);
            }
         }
         if(_loc1_ != 0)
         {
            _loc2_ = li32(cmodule.ccode._px);
            if(_loc2_ == 0)
            {
               si32(_loc1_,cmodule.ccode._px);
            }
            else
            {
               cmodule.ccode.mstate.esp -= 4;
               si32(_loc1_,cmodule.ccode.mstate.esp);
               cmodule.ccode.mstate.esp -= 4;
               FSM_ifree.start();
               cmodule.ccode.mstate.esp += 4;
            }
         }
         cmodule.ccode.mstate.eax = _loc4_;
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

