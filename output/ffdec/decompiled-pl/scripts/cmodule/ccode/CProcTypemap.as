package cmodule.ccode
{
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   internal class CProcTypemap extends CTypemap
   {
      
      private var retTypemap:CTypemap;
      
      private var varargs:Boolean;
      
      private var argTypemaps:Array;
      
      private var async:Boolean;
      
      public function CProcTypemap(param1:CTypemap, param2:Array, param3:Boolean = false, param4:Boolean = false)
      {
         super();
         this.retTypemap = param1;
         this.argTypemaps = param2;
         this.varargs = param3;
         this.async = param4;
      }
      
      override public function createC(param1:*, param2:int = 0) : Array
      {
         var v:* = param1;
         var ptr:int = param2;
         var id:int = cmodule.ccode.regFunc(function():void
         {
            var sp:*;
            var n:*;
            var tm:* = undefined;
            var aa:* = undefined;
            var ts:* = undefined;
            var args:* = [];
            cmodule.ccode.mstate.pop();
            sp = cmodule.ccode.mstate.esp;
            n = 0;
            while(n < argTypemaps.length)
            {
               tm = argTypemaps[n];
               aa = [];
               ts = tm.typeSize;
               cmodule.ccode.mstate.ds.position = sp;
               sp += ts;
               while(ts)
               {
                  aa.push(cmodule.ccode.mstate.ds.readInt());
                  ts -= 4;
               }
               args.push(tm.fromC(aa));
               n++;
            }
            if(varargs)
            {
               args.push(sp);
            }
            try
            {
               retTypemap.toReturnRegs(cmodule.ccode.mstate,v.apply(null,args));
            }
            catch(e:*)
            {
               cmodule.ccode.mstate.eax = 0;
               cmodule.ccode.mstate.edx = 0;
               cmodule.ccode.mstate.st0 = 0;
               cmodule.ccode.log(2,"v.apply: " + e.toString());
            }
         });
         return [id];
      }
      
      override public function destroyC(param1:Array) : void
      {
         cmodule.ccode.unregFunc(int(param1[0]));
      }
      
      override public function fromC(param1:Array) : *
      {
         var v:Array = param1;
         return function(... rest):*
         {
            var sp:* = undefined;
            var cargs:* = undefined;
            var n:* = undefined;
            var asyncHandler:* = undefined;
            var oldWorker:* = undefined;
            var arg:* = undefined;
            var carg:* = undefined;
            var args:Array = rest;
            var cleanup:Function = function():void
            {
               n = cargs.length - 1;
               while(n >= 0)
               {
                  argTypemaps[n].destroyC(cargs[n]);
                  --n;
               }
               cmodule.ccode.mstate.esp = sp;
               cmodule.ccode.mstate.gworker = oldWorker;
            };
            sp = cmodule.ccode.mstate.esp;
            cargs = [];
            oldWorker = cmodule.ccode.mstate.gworker;
            if(async)
            {
               asyncHandler = args.shift();
               cmodule.ccode.mstate.gworker = new NotifyMachine(function():Boolean
               {
                  var result:* = retTypemap.fromReturnRegs(cmodule.ccode.mstate);
                  cleanup();
                  try
                  {
                     asyncHandler(result);
                  }
                  catch(e:*)
                  {
                     cmodule.ccode.log(1,"asyncHandler: " + e.toString());
                  }
                  return true;
               });
            }
            n = args.length - 1;
            while(n >= 0)
            {
               arg = args[n];
               if(n >= argTypemaps.length)
               {
                  push(arg);
               }
               else
               {
                  carg = argTypemaps[n].createC(arg);
                  cargs[n] = carg;
                  push(carg);
               }
               n--;
            }
            cmodule.ccode.mstate.push(0);
            if(asyncHandler)
            {
               try
               {
                  cmodule.ccode.mstate.funcs[int(v[0])]();
               }
               catch(e:AlchemyYield)
               {
               }
               catch(e:AlchemyDispatch)
               {
               }
               catch(e:AlchemyBlock)
               {
               }
               catch(e:*)
               {
                  cleanup();
                  throw e;
               }
               return;
            }
            try
            {
               try
               {
                  cmodule.ccode.mstate.funcs[int(v[0])]();
               }
               catch(e:AlchemyYield)
               {
               }
               catch(e:AlchemyDispatch)
               {
               }
               while(cmodule.ccode.mstate.gworker !== oldWorker)
               {
                  try
                  {
                     while(cmodule.ccode.mstate.gworker !== oldWorker)
                     {
                        cmodule.ccode.mstate.gworker.work();
                     }
                  }
                  catch(e:AlchemyYield)
                  {
                  }
                  catch(e:AlchemyDispatch)
                  {
                  }
               }
               return retTypemap.fromReturnRegs(cmodule.ccode.mstate);
            }
            finally
            {
               cleanup();
            }
         };
      }
      
      private function push(param1:*) : void
      {
         var _loc2_:* = 0;
         if(param1 is Array)
         {
            _loc2_ = int(param1.length - 1);
            while(_loc2_ >= 0)
            {
               cmodule.ccode.mstate.push(param1[_loc2_]);
               _loc2_--;
            }
         }
         else
         {
            cmodule.ccode.mstate.push(param1);
         }
      }
   }
}

