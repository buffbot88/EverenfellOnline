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
   
   public final class FSM___multadd_D2A extends Machine
   {
      
      public static const intRegCount:int = 12;
      
      public static const NumberRegCount:int = 0;
      
      public var i10:int;
      
      public var i11:int;
      
      public var i0:int;
      
      public var i1:int;
      
      public var i2:int;
      
      public var i3:int;
      
      public var i4:int;
      
      public var i5:int;
      
      public var i6:int;
      
      public var i7:int;
      
      public var i8:int;
      
      public var i9:int;
      
      public function FSM___multadd_D2A()
      {
         super();
      }
      
      public static function start() : void
      {
         var _loc1_:FSM___multadd_D2A = null;
         _loc1_ = new FSM___multadd_D2A();
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
               this.i0 = 0;
               this.i1 = li32(mstate.ebp + 8);
               this.i2 = li32(mstate.ebp + 12);
               this.i3 = li32(this.i1 + 16);
               this.i4 = this.i2 >> 31;
               this.i5 = this.i1 + 20;
               this.i6 = this.i1 + 16;
               this.i7 = this.i0;
               this.i8 = this.i0;
               this.i9 = 0;
               mstate.esp -= 16;
               this.i10 = li32(this.i5);
               si32(this.i10,mstate.esp);
               si32(this.i9,mstate.esp + 4);
               si32(this.i2,mstate.esp + 8);
               si32(this.i4,mstate.esp + 12);
               mstate.esp -= 4;
               mstate.funcs[cmodule.ccode.___muldi3]();
            case 1:
               while(true)
               {
                  this.i10 = mstate.eax;
                  this.i11 = mstate.edx;
                  this.i7 = cmodule.ccode.__addc(this.i10,this.i7);
                  this.i0 = cmodule.ccode.__adde(this.i11,this.i0);
                  si32(this.i7,this.i5);
                  this.i5 += 4;
                  this.i7 = this.i8 + 1;
                  mstate.esp += 16;
                  this.i8 = this.i0;
                  if(this.i7 >= this.i3)
                  {
                     this.i2 = this.i8 == 0 ? 1 : 0;
                     if(this.i2 == 0)
                     {
                        this.i2 = li32(this.i1 + 8);
                        if(this.i2 <= this.i3)
                        {
                           this.i2 = li32(this.i1 + 4);
                           mstate.esp -= 4;
                           this.i2 += 1;
                           si32(this.i2,mstate.esp);
                           state = 2;
                           mstate.esp -= 4;
                           FSM___Balloc_D2A.start();
                           return;
                        }
                        this.i2 = this.i3 << 2;
                        this.i2 = this.i1 + this.i2;
                        si32(this.i0,this.i2 + 20);
                        this.i0 = this.i3 + 1;
                        si32(this.i0,this.i1 + 16);
                     }
                     mstate.eax = this.i1;
                     mstate.esp = mstate.ebp;
                     mstate.ebp = li32(mstate.esp);
                     mstate.esp += 4;
                     mstate.esp += 4;
                     mstate.gworker = caller;
                     return;
                  }
                  this.i8 = this.i7;
                  this.i7 = this.i0;
                  this.i0 = this.i9;
                  this.i9 = 0;
                  mstate.esp -= 16;
                  this.i10 = li32(this.i5);
                  si32(this.i10,mstate.esp);
                  si32(this.i9,mstate.esp + 4);
                  si32(this.i2,mstate.esp + 8);
                  si32(this.i4,mstate.esp + 12);
                  mstate.esp -= 4;
                  mstate.funcs[cmodule.ccode.___muldi3]();
               }
               break;
            case 2:
               this.i2 = mstate.eax;
               mstate.esp += 4;
               this.i4 = li32(this.i6);
               this.i5 = this.i2 + 12;
               this.i4 <<= 2;
               this.i6 = this.i1 + 12;
               this.i4 += 8;
               cmodule.ccode.memcpy(this.i5,this.i6,this.i4);
               this.i4 = this.i1 + 4;
               if(this.i1 == 0)
               {
                  this.i1 = this.i2;
               }
               else
               {
                  this.i5 = cmodule.ccode._freelist;
                  this.i4 = li32(this.i4);
                  this.i4 <<= 2;
                  this.i4 = this.i5 + this.i4;
                  this.i5 = li32(this.i4);
                  si32(this.i5,this.i1);
                  si32(this.i1,this.i4);
                  this.i1 = this.i2;
               }
               §§goto(addr0315);
         }
         throw "Invalid state in ___multadd_D2A";
      }
   }
}

