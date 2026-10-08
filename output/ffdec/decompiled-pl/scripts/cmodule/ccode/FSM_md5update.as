package cmodule.ccode
{
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.li8;
   import avm2.intrinsics.memory.si32;
   import avm2.intrinsics.memory.si8;
   
   public final class FSM_md5update extends Machine
   {
      
      public function FSM_md5update()
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
         _loc1_ = li32(cmodule.ccode.mstate.ebp + 16);
         _loc2_ = li32(cmodule.ccode.mstate.ebp + 8);
         _loc3_ = li32(_loc2_ + 16);
         _loc4_ = _loc1_ << 3;
         _loc5_ = _loc3_ + _loc4_;
         _loc3_ >>>= 3;
         si32(_loc5_,_loc2_ + 16);
         _loc6_ = li32(cmodule.ccode.mstate.ebp + 12);
         _loc3_ &= 63;
         _loc7_ = _loc2_;
         if(uint(_loc5_) < uint(_loc4_))
         {
            _loc4_ = li32(_loc2_ + 20);
            _loc4_ = _loc4_ + 1;
            si32(_loc4_,_loc2_ + 20);
         }
         _loc4_ = li32(_loc2_ + 20);
         _loc5_ = _loc1_ >>> 29;
         _loc4_ += _loc5_;
         si32(_loc4_,_loc2_ + 20);
         _loc4_ = 64 - _loc3_;
         if(uint(_loc4_) > uint(_loc1_))
         {
            _loc2_ = 0;
         }
         else
         {
            _loc5_ = 0;
            _loc8_ = _loc3_ + _loc7_;
            do
            {
               _loc9_ = _loc6_ + _loc5_;
               _loc9_ = li8(_loc9_);
               _loc10_ = _loc8_ + _loc5_;
               si8(_loc9_,_loc10_ + 24);
               _loc5_ += 1;
            }
            while(uint(_loc5_) < uint(_loc4_));
            cmodule.ccode.mstate.esp -= 8;
            _loc5_ = _loc2_ + 24;
            si32(_loc2_,cmodule.ccode.mstate.esp);
            si32(_loc5_,cmodule.ccode.mstate.esp + 4);
            cmodule.ccode.mstate.esp -= 4;
            FSM_md5transform.start();
            cmodule.ccode.mstate.esp += 8;
            _loc5_ = _loc4_ + 63;
            if(uint(_loc5_) >= uint(_loc1_))
            {
               _loc3_ = 0;
               _loc2_ = _loc4_;
            }
            else
            {
               _loc4_ = _loc6_ + 64;
               _loc3_ = 0 - _loc3_;
               while(true)
               {
                  cmodule.ccode.mstate.esp -= 8;
                  _loc5_ = _loc4_ + _loc3_;
                  si32(_loc2_,cmodule.ccode.mstate.esp);
                  si32(_loc5_,cmodule.ccode.mstate.esp + 4);
                  cmodule.ccode.mstate.esp -= 4;
                  FSM_md5transform.start();
                  cmodule.ccode.mstate.esp += 8;
                  _loc5_ = _loc3_ + 64;
                  _loc3_ += 191;
                  if(uint(_loc3_) >= uint(_loc1_))
                  {
                     break;
                  }
                  _loc3_ = _loc5_;
               }
               _loc3_ = 0;
               _loc2_ = _loc5_ + 64;
            }
         }
         _loc4_ = _loc1_ - _loc2_;
         if(_loc2_ != _loc1_)
         {
            _loc1_ = 0;
            _loc3_ += _loc7_;
            _loc2_ += _loc6_;
            do
            {
               _loc5_ = _loc2_ + _loc1_;
               _loc5_ = li8(_loc5_);
               _loc6_ = _loc3_ + _loc1_;
               si8(_loc5_,_loc6_ + 24);
               _loc1_ += 1;
            }
            while(uint(_loc1_) < uint(_loc4_));
         }
         cmodule.ccode.mstate.esp = cmodule.ccode.mstate.ebp;
         cmodule.ccode.mstate.ebp = li32(cmodule.ccode.mstate.esp);
         cmodule.ccode.mstate.esp += 4;
         cmodule.ccode.mstate.esp += 4;
      }
   }
}

