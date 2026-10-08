package cmodule.ccode
{
   import avm2.intrinsics.memory.li16;
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM__cleanup extends Machine
   {
      
      public static const intRegCount:int = 6;
      
      public static const NumberRegCount:int = 0;
      
      public var i0:int;
      
      public var i1:int;
      
      public var i2:int;
      
      public var i3:int;
      
      public var i4:int;
      
      public var i5:int;
      
      public function FSM__cleanup()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:FSM__cleanup = null;
         _loc1_ = new FSM__cleanup();
         cmodule.ccode.gstate.gworker = _loc1_;
      }
      
      final override public function work() : void
      {
         switch(state)
         {
            case 0:
               mstate.esp -= 4;
               si32(mstate.ebp,mstate.esp);
               mstate.ebp = mstate.esp;
               mstate.esp -= 0;
               this.i0 = cmodule.ccode.___sglue;
               this.i1 = 0;
               addr005b:
               this.i2 = li32(this.i0 + 4);
               this.i3 = li32(this.i0 + 8);
               this.i4 = this.i2 + -1;
               if(this.i4 <= -1)
               {
                  while(true)
                  {
                     this.i0 = li32(this.i0);
                     if(this.i0 == 0)
                     {
                        mstate.esp = mstate.ebp;
                        mstate.ebp = li32(mstate.esp);
                        mstate.esp += 4;
                        mstate.esp += 4;
                        mstate.gworker = caller;
                        return;
                     }
                     §§goto(addr005b);
                  }
                  addr010f:
                  this.i4 = mstate.eax;
                  mstate.esp += 4;
                  this.i1 = this.i4 | this.i1;
                  while(true)
                  {
                     this.i3 += 88;
                     this.i2 += -1;
                     if(this.i2 <= -1)
                     {
                        §§goto(addr015a);
                     }
                     addr009d:
                     this.i4 = li16(this.i3 + 12);
                     this.i4 <<= 16;
                     this.i4 >>= 16;
                     this.i5 = this.i3;
                     if(this.i4 > 0)
                     {
                        mstate.esp -= 4;
                        si32(this.i5,mstate.esp);
                        state = 1;
                        mstate.esp -= 4;
                        FSM___sflush.start();
                        return;
                     }
                  }
                  addr015a:
                  break;
               }
               this.i2 += -1;
               §§goto(addr009d);
            case 1:
               §§goto(addr010f);
         }
         throw "Invalid state in __cleanup";
      }
   }
}

