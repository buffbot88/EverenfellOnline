package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.li8;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM_getenv extends Machine
   {
      
      public function FSM_getenv()
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
         _loc2_ = _loc1_;
         loop3:
         while(true)
         {
            if(_loc1_ != 0)
            {
               _loc3_ = li32(cmodule.ccode._environ);
               _loc4_ = _loc3_;
               if(_loc3_ != 0)
               {
                  while(true)
                  {
                     _loc5_ = li8(_loc1_);
                     if(_loc5_ != 0)
                     {
                        _loc5_ &= 255;
                        if(_loc5_ != 61)
                        {
                           _loc1_ = _loc2_;
                           while(true)
                           {
                              _loc5_ = li8(_loc1_ + 1);
                              _loc1_ += 1;
                              _loc6_ = _loc1_;
                              if(_loc5_ == 0)
                              {
                                 break;
                              }
                              _loc5_ &= 255;
                              if(_loc5_ == 61)
                              {
                                 break;
                              }
                              _loc1_ = _loc6_;
                           }
                           break;
                        }
                     }
                     break;
                  }
                  _loc4_ = li32(_loc4_);
                  if(_loc4_ != 0)
                  {
                     _loc3_ += 4;
                     _loc1_ -= _loc2_;
                     loop1:
                     while(true)
                     {
                        _loc5_ = 0;
                        _loc6_ = _loc3_;
                        while(true)
                        {
                           _loc8_ = _loc2_ + _loc5_;
                           _loc7_ = _loc4_ + _loc5_;
                           if(_loc1_ == _loc5_)
                           {
                              break;
                           }
                           _loc7_ = li8(_loc7_);
                           if(_loc7_ != 0)
                           {
                              _loc8_ = li8(_loc8_);
                              _loc9_ = _loc5_ + 1;
                              _loc7_ &= 255;
                              if(_loc7_ == _loc8_)
                              {
                                 continue;
                              }
                              addr01b8:
                              _loc4_ += _loc9_;
                           }
                           else
                           {
                              _loc4_ += _loc5_;
                           }
                           if(_loc1_ == _loc5_)
                           {
                              _loc5_ = li8(_loc4_);
                              _loc4_ += 1;
                              if(_loc5_ == 61)
                              {
                                 _loc1_ = _loc4_;
                                 break loop3;
                              }
                           }
                           _loc4_ = li32(_loc6_);
                           _loc3_ += 4;
                           if(_loc4_ != 0)
                           {
                              continue loop1;
                           }
                           _loc5_ = _loc9_;
                        }
                        _loc4_ += _loc5_;
                        §§goto(addr01b8);
                     }
                     break;
                  }
               }
            }
            _loc1_ = 0;
            break;
         }
         cmodule.ccode.mstate.eax = _loc1_;
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

