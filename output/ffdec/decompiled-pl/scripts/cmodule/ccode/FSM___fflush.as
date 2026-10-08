package cmodule.ccode
{
   import avm2.intrinsics.memory.li16;
   import avm2.intrinsics.memory.li32;
   import avm2.intrinsics.memory.si32;
   
   public final class FSM___fflush extends Machine
   {
      
      public static const intRegCount:int = 6;
      
      public static const NumberRegCount:int = 0;
      
      public var i0:int;
      
      public var i1:int;
      
      public var i2:int;
      
      public var i3:int;
      
      public var i4:int;
      
      public var i5:int;
      
      public function FSM___fflush()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:FSM___fflush = null;
         _loc1_ = new FSM___fflush();
         cmodule.ccode.gstate.gworker = _loc1_;
      }
      
      final override public function work() : void
      {
         loop2:
         switch(state)
         {
            case 0:
               mstate.esp -= 4;
               si32(mstate.ebp,mstate.esp);
               mstate.ebp = mstate.esp;
               mstate.esp -= 0;
               this.i0 = li32(mstate.ebp + 8);
               if(this.i0 == 0)
               {
                  this.i0 = cmodule.ccode.___sglue;
                  this.i1 = 0;
                  this.i2 = li32(this.i0 + 4);
                  this.i3 = li32(this.i0 + 8);
                  this.i4 = this.i2 + -1;
                  if(this.i4 <= -1)
                  {
                     do
                     {
                        this.i0 = li32(this.i0);
                        if(this.i0 == 0)
                        {
                           addr018f:
                           mstate.eax = this.i1;
                           break loop2;
                        }
                        this.i2 = li32(this.i0 + 4);
                        this.i3 = li32(this.i0 + 8);
                        this.i4 = this.i2 + -1;
                     }
                     while(this.i4 <= -1);
                     addr0177:
                  }
                  this.i2 += -1;
                  addr00ba:
                  this.i4 = li16(this.i3 + 12);
                  this.i4 <<= 16;
                  this.i4 >>= 16;
                  this.i5 = this.i3;
                  if(this.i4 <= 0)
                  {
                     while(true)
                     {
                        this.i3 += 88;
                        this.i2 += -1;
                        if(this.i2 <= -1)
                        {
                           §§goto(addr0177);
                        }
                        §§goto(addr00ba);
                     }
                     §§goto(addr018f);
                     addr0152:
                  }
                  mstate.esp -= 4;
                  si32(this.i5,mstate.esp);
                  state = 1;
                  mstate.esp -= 4;
                  FSM___sflush.start();
                  return;
               }
               this.i1 = li16(this.i0 + 12);
               this.i1 &= 24;
               if(this.i1 == 0)
               {
                  this.i0 = 9;
                  si32(this.i0,cmodule.ccode._val_2E_939);
                  this.i0 = -1;
                  addr021c:
                  mstate.eax = this.i0;
                  break;
               }
               mstate.esp -= 4;
               si32(this.i0,mstate.esp);
               state = 2;
               mstate.esp -= 4;
               FSM___sflush.start();
               return;
               break;
            case 1:
               this.i4 = mstate.eax;
               mstate.esp += 4;
               this.i1 = this.i4 | this.i1;
               §§goto(addr0152);
            case 2:
               this.i0 = mstate.eax;
               mstate.esp += 4;
               §§goto(addr021c);
            default:
               throw "Invalid state in ___fflush";
         }
         mstate.esp = mstate.ebp;
         mstate.ebp = li32(mstate.esp);
         mstate.esp += 4;
         mstate.esp += 4;
         mstate.gworker = caller;
      }
   }
}

