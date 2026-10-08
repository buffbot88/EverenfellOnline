package cmodule.ccode
{
   import avm2.intrinsics.memory.li16;
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.li8;
   import avm2.intrinsics.memory.si16;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM_ifree extends Machine
   {
      
      public function FSM_ifree()
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
         _loc1_ = li32(cmodule.ccode.mstate.ebp + 8);
         while(true)
         {
            _loc3_ = _loc1_;
            if(_loc3_ == 0)
            {
               break;
            }
            _loc1_ = li32(cmodule.ccode._malloc_origo);
            _loc2_ = _loc3_ >>> 12;
            _loc4_ = _loc2_ - _loc1_;
            _loc5_ = _loc3_;
            if(uint(_loc4_) < uint(12))
            {
               break;
            }
            _loc6_ = li32(cmodule.ccode._last_index);
            if(uint(_loc4_) > uint(_loc6_))
            {
               break;
            }
            _loc6_ = li32(cmodule.ccode._page_dir);
            _loc7_ = _loc4_ << 2;
            _loc7_ = _loc6_ + _loc7_;
            _loc8_ = li32(_loc7_);
            _loc9_ = _loc6_;
            if(uint(_loc8_) <= uint(3))
            {
               if(_loc8_ != 2)
               {
                  break;
               }
               if(_loc8_ == 1)
               {
                  break;
               }
               _loc5_ &= 4095;
               if(_loc5_ != 0)
               {
                  break;
               }
               _loc5_ = 1;
               _loc8_ = _loc4_ << 2;
               si32(_loc5_,_loc7_);
               _loc5_ = _loc8_ + _loc9_;
               _loc5_ = li32(_loc5_ + 4);
               if(_loc5_ != 3)
               {
                  _loc1_ = 4096;
               }
               else
               {
                  _loc5_ = 1;
                  _loc1_ = _loc2_ - _loc1_;
                  _loc1_ <<= 2;
                  _loc8_ = _loc6_;
                  do
                  {
                     _loc2_ = 1;
                     _loc4_ = _loc1_ + _loc8_;
                     si32(_loc2_,_loc4_ + 4);
                     _loc2_ = li32(_loc4_ + 8);
                     _loc8_ += 4;
                     _loc5_ += 1;
                  }
                  while(_loc2_ == 3);
                  _loc1_ = _loc5_ << 12;
               }
               _loc5_ = _loc1_;
               _loc1_ = li8(cmodule.ccode._malloc_junk_2E_b);
               _loc1_ ^= 1;
               _loc1_ &= 1;
               if(_loc1_ == 0)
               {
                  _loc1_ = -48;
                  _loc8_ = _loc3_;
                  _loc2_ = _loc5_;
                  cmodule.ccode.memset(_loc8_,_loc1_,_loc2_);
               }
               _loc1_ = li8(cmodule.ccode._malloc_hint_2E_b);
               _loc1_ ^= 1;
               _loc1_ &= 1;
               if(_loc1_ == 0)
               {
                  _loc1_ = cmodule.ccode.__2E_str4;
                  _loc2_ = _loc8_ = 4;
                  cmodule.ccode.log(_loc2_,cmodule.ccode.mstate.gworker.stringFromPtr(_loc1_));
               }
               _loc1_ = li32(cmodule.ccode._px);
               _loc8_ = _loc3_ + _loc5_;
               if(_loc1_ != 0)
               {
                  _loc2_ = _loc1_;
               }
               else
               {
                  _loc1_ = 20;
                  cmodule.ccode.mstate.esp -= 4;
                  si32(_loc1_,cmodule.ccode.mstate.esp);
                  cmodule.ccode.mstate.esp -= 4;
                  FSM_imalloc.start();
                  _loc1_ = int(cmodule.ccode.mstate.eax);
                  cmodule.ccode.mstate.esp += 4;
                  si32(_loc1_,cmodule.ccode._px);
                  _loc2_ = _loc1_;
               }
               si32(_loc3_,_loc1_ + 8);
               si32(_loc8_,_loc2_ + 12);
               si32(_loc5_,_loc2_ + 16);
               _loc1_ = li32(cmodule.ccode._free_list);
               while(true)
               {
                  if(_loc1_ != 0)
                  {
                     _loc4_ = li32(_loc1_ + 12);
                     if(uint(_loc4_) < uint(_loc3_))
                     {
                        do
                        {
                           _loc4_ = _loc1_;
                           _loc1_ = li32(_loc4_);
                           if(_loc1_ == 0)
                           {
                              _loc1_ = _loc4_;
                              break;
                           }
                           _loc4_ = li32(_loc1_ + 12);
                        }
                        while(uint(_loc4_) < uint(_loc3_));
                     }
                     _loc4_ = li32(_loc1_ + 8);
                     _loc6_ = _loc1_ + 8;
                     if(uint(_loc4_) > uint(_loc8_))
                     {
                        _loc5_ = 0;
                        si32(_loc1_,_loc2_);
                        _loc8_ = li32(_loc1_ + 4);
                        si32(_loc8_,_loc2_ + 4);
                        si32(_loc2_,_loc1_ + 4);
                        _loc1_ = li32(_loc2_ + 4);
                        si32(_loc2_,_loc1_);
                        si32(_loc5_,cmodule.ccode._px);
                        _loc1_ = _loc2_;
                     }
                     else
                     {
                        _loc7_ = li32(_loc1_ + 12);
                        _loc9_ = _loc1_ + 12;
                        loop7:
                        while(true)
                        {
                           while(true)
                           {
                              if(_loc7_ == _loc3_)
                              {
                                 _loc8_ = _loc7_ + _loc5_;
                                 si32(_loc8_,_loc9_);
                                 _loc2_ = li32(_loc1_ + 16);
                                 _loc5_ = _loc2_ + _loc5_;
                                 si32(_loc5_,_loc1_ + 16);
                                 _loc2_ = li32(_loc1_);
                                 _loc3_ = _loc1_ + 16;
                                 _loc4_ = _loc1_;
                                 if(_loc2_ == 0)
                                 {
                                    break;
                                 }
                                 _loc6_ = li32(_loc2_ + 8);
                                 if(_loc8_ == _loc6_)
                                 {
                                    _loc8_ = li32(_loc2_ + 12);
                                    si32(_loc8_,_loc9_);
                                    _loc8_ = li32(_loc2_ + 16);
                                    _loc5_ = _loc8_ + _loc5_;
                                    si32(_loc5_,_loc3_);
                                    _loc5_ = li32(_loc2_);
                                    si32(_loc5_,_loc4_);
                                    if(_loc5_ == 0)
                                    {
                                       _loc5_ = _loc2_;
                                       break loop7;
                                    }
                                    si32(_loc1_,_loc5_ + 4);
                                    _loc5_ = _loc2_;
                                    break loop7;
                                 }
                              }
                              else
                              {
                                 if(_loc4_ == _loc8_)
                                 {
                                    _loc2_ = 0;
                                    _loc8_ = li32(_loc1_ + 16);
                                    _loc5_ = _loc8_ + _loc5_;
                                    si32(_loc5_,_loc1_ + 16);
                                    si32(_loc3_,_loc6_);
                                    _loc5_ = _loc2_;
                                    break loop7;
                                 }
                                 _loc5_ = li32(_loc1_);
                                 _loc3_ = _loc1_;
                                 if(_loc5_ == 0)
                                 {
                                    _loc5_ = 0;
                                    si32(_loc5_,_loc2_);
                                    si32(_loc1_,_loc2_ + 4);
                                    si32(_loc2_,_loc3_);
                                    si32(_loc5_,cmodule.ccode._px);
                                    _loc1_ = _loc2_;
                                    break loop7;
                                 }
                              }
                              break;
                           }
                           _loc5_ = 0;
                           break;
                        }
                     }
                     break loop7;
                  }
                  _loc5_ = cmodule.ccode._free_list;
                  si32(_loc1_,_loc2_);
                  si32(_loc5_,_loc2_ + 4);
                  si32(_loc2_,cmodule.ccode._free_list);
                  _loc1_ = 0;
                  si32(_loc1_,cmodule.ccode._px);
                  _loc1_ = li32(_loc2_);
                  if(_loc1_ != 0)
                  {
                     _loc1_ = 0;
                     break;
                  }
                  _loc1_ = 0;
                  _loc5_ = _loc2_;
                  _loc3_ = _loc5_;
                  _loc5_ = li32(_loc3_ + 16);
                  _loc8_ = li32(cmodule.ccode._malloc_cache);
                  _loc2_ = _loc3_ + 16;
                  if(uint(_loc5_) > uint(_loc8_))
                  {
                     _loc5_ = li32(_loc3_ + 12);
                     _loc8_ = li32(cmodule.ccode._malloc_brk);
                     _loc4_ = _loc3_ + 12;
                     if(_loc5_ == _loc8_)
                     {
                        _loc5_ = 0;
                        _loc5_ = cmodule.ccode._sbrk(_loc5_);
                        _loc8_ = li32(cmodule.ccode._malloc_brk);
                        if(_loc5_ == _loc8_)
                        {
                           _loc3_ = li32(_loc3_ + 8);
                           _loc5_ = li32(cmodule.ccode._malloc_cache);
                           _loc3_ += _loc5_;
                           si32(_loc3_,_loc4_);
                           si32(_loc5_,_loc2_);
                           _loc3_ = cmodule.ccode._brk(_loc3_);
                           _loc3_ = li32(_loc4_);
                           si32(_loc3_,cmodule.ccode._malloc_brk);
                           _loc5_ = li32(cmodule.ccode._malloc_origo);
                           _loc8_ = li32(cmodule.ccode._last_index);
                           _loc3_ >>>= 12;
                           _loc2_ = _loc3_ - _loc5_;
                           if(uint(_loc2_) <= uint(_loc8_))
                           {
                              _loc3_ -= _loc5_;
                              _loc5_ = li32(cmodule.ccode._page_dir);
                              _loc4_ = _loc3_ << 2;
                              _loc5_ += _loc4_;
                              do
                              {
                                 _loc4_ = 0;
                                 si32(_loc4_,_loc5_);
                                 _loc5_ += 4;
                                 _loc3_ += 1;
                              }
                              while(uint(_loc3_) <= uint(_loc8_));
                           }
                           _loc3_ = _loc2_ + -1;
                           si32(_loc3_,cmodule.ccode._last_index);
                           break;
                        }
                     }
                  }
                  break;
               }
               if(_loc1_ == 0)
               {
                  break;
               }
            }
            else
            {
               _loc1_ = li16(_loc8_ + 8);
               _loc2_ = li16(_loc8_ + 10);
               _loc4_ = _loc5_ & 0x0FFF;
               _loc2_ = _loc4_ >>> _loc2_;
               _loc4_ = _loc8_ + 10;
               _loc6_ = _loc1_ + -1;
               _loc5_ = _loc6_ & _loc5_;
               if(_loc5_ != 0)
               {
                  break;
               }
               _loc5_ = 1;
               _loc6_ = _loc2_ & -32;
               _loc6_ = _loc6_ >>> 3;
               _loc6_ = _loc8_ + _loc6_;
               _loc2_ &= 31;
               _loc7_ = li32(_loc6_ + 16);
               _loc2_ = _loc5_ << _loc2_;
               _loc5_ = _loc6_ + 16;
               _loc6_ = _loc7_ & _loc2_;
               if(_loc6_ != 0)
               {
                  break;
               }
               _loc6_ = li8(cmodule.ccode._malloc_junk_2E_b);
               _loc6_ = _loc6_ ^ 1;
               _loc6_ = _loc6_ & 1;
               if(_loc6_ == 0)
               {
                  _loc6_ = -48;
                  cmodule.ccode.memset(_loc3_,_loc6_,_loc1_);
               }
               _loc1_ = li32(_loc5_);
               _loc1_ |= _loc2_;
               si32(_loc1_,_loc5_);
               _loc1_ = li16(_loc8_ + 12);
               _loc2_ = _loc1_ + 1;
               si16(_loc2_,_loc8_ + 12);
               _loc3_ = li16(_loc4_);
               _loc4_ = li32(cmodule.ccode._page_dir);
               _loc3_ <<= 2;
               _loc3_ = _loc4_ + _loc3_;
               if(_loc1_ == 0)
               {
                  _loc1_ = li32(_loc3_);
                  if(_loc1_ == 0)
                  {
                     _loc1_ = _loc3_;
                  }
                  else
                  {
                     _loc1_ = _loc8_ + 4;
                     _loc2_ = _loc3_;
                     while(true)
                     {
                        _loc3_ = li32(_loc2_);
                        _loc4_ = li32(_loc3_);
                        if(_loc4_ == 0)
                        {
                           _loc1_ = _loc2_;
                           break;
                        }
                        _loc5_ = li32(_loc4_ + 4);
                        _loc6_ = li32(_loc1_);
                        _loc2_ = uint(_loc5_) < uint(_loc6_) ? _loc3_ : _loc2_;
                        _loc5_ = uint(_loc5_) >= uint(_loc6_) ? 1 : 0;
                        if(_loc4_ != 0)
                        {
                           _loc4_ = _loc5_ & 1;
                           if(_loc4_ == 0)
                           {
                              continue;
                           }
                        }
                        _loc1_ = _loc2_;
                        break;
                        _loc2_ = _loc3_;
                     }
                  }
                  _loc2_ = li32(_loc1_);
                  si32(_loc2_,_loc8_);
                  si32(_loc8_,_loc1_);
                  break;
               }
               _loc1_ = li16(_loc8_ + 14);
               _loc2_ &= 65535;
               if(_loc2_ != _loc1_)
               {
                  break;
               }
               _loc1_ = li32(_loc3_);
               if(_loc1_ != _loc8_)
               {
                  _loc1_ = _loc3_;
                  do
                  {
                     _loc1_ = li32(_loc1_);
                     _loc2_ = li32(_loc1_);
                  }
                  while(_loc2_ != _loc8_);
               }
               else
               {
                  _loc1_ = _loc3_;
               }
               _loc2_ = 2;
               _loc3_ = li32(_loc8_);
               si32(_loc3_,_loc1_);
               _loc1_ = li32(_loc8_ + 4);
               _loc3_ = li32(cmodule.ccode._malloc_origo);
               _loc1_ >>>= 12;
               _loc1_ -= _loc3_;
               _loc1_ <<= 2;
               _loc1_ = _loc4_ + _loc1_;
               si32(_loc2_,_loc1_);
               _loc1_ = li32(_loc8_ + 4);
               _loc2_ = _loc8_;
               if(_loc1_ != _loc8_)
               {
                  cmodule.ccode.mstate.esp -= 4;
                  si32(_loc2_,cmodule.ccode.mstate.esp);
                  cmodule.ccode.mstate.esp -= 4;
                  FSM_ifree.start();
                  cmodule.ccode.mstate.esp += 4;
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

