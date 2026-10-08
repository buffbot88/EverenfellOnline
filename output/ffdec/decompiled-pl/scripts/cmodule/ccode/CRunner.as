package cmodule.ccode
{
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   public class CRunner implements Debuggee
   {
      
      internal var timer:Timer;
      
      internal var forceSyncSystem:Boolean;
      
      internal var suspended:int = 0;
      
      internal var debugger:GDBMIDebugger;
      
      public function CRunner(param1:Boolean = false)
      {
         super();
         if(cmodule.ccode.grunner)
         {
            cmodule.ccode.log(1,"More than one CRunner!");
         }
         cmodule.ccode.grunner = this;
         this.forceSyncSystem = param1;
      }
      
      public function cancelDebug() : void
      {
         this.debugger = null;
      }
      
      public function get isRunning() : Boolean
      {
         return this.suspended <= 0;
      }
      
      public function createArgv(param1:Array) : Array
      {
         return this.rawAllocStringArray(param1).concat(0);
      }
      
      public function createEnv(param1:Object) : Array
      {
         var _loc3_:String = null;
         var _loc2_:Array = [];
         for(_loc3_ in param1)
         {
            _loc2_.push(_loc3_ + "=" + param1[_loc3_]);
         }
         return this.rawAllocStringArray(_loc2_).concat(0);
      }
      
      public function startInit() : void
      {
         var argv:Array;
         var envp:Array;
         var args:Array;
         var ap:int;
         var env:Object;
         var startArgs:Array;
         cmodule.ccode.log(2,"Static init...");
         cmodule.ccode.modStaticInit();
         args = cmodule.ccode.gstate.system.getargv();
         env = cmodule.ccode.gstate.system.getenv();
         argv = this.createArgv(args);
         envp = this.createEnv(env);
         startArgs = [args.length].concat(argv,envp);
         ap = this.rawAllocIntArray(startArgs);
         cmodule.ccode.gstate.ds.length = cmodule.ccode.gstate.ds.length + 4095 & ~0x0FFF;
         cmodule.ccode.gstate.push(ap);
         cmodule.ccode.gstate.push(0);
         cmodule.ccode.log(2,"Starting work...");
         this.timer = new Timer(1);
         this.timer.addEventListener(TimerEvent.TIMER,function(param1:TimerEvent):void
         {
            work();
         });
         try
         {
            FSM__start.start();
         }
         catch(e:AlchemyExit)
         {
            cmodule.ccode.gstate.system.exit(e.rv);
            return;
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
         this.startWork();
      }
      
      private function startWork() : void
      {
         if(!this.timer.running)
         {
            this.timer.delay = 1;
            this.timer.start();
         }
      }
      
      public function work() : void
      {
         var startTime:Number = NaN;
         var checkInterval:int = 0;
         var ms:int = 0;
         if(!this.isRunning)
         {
            return;
         }
         try
         {
            startTime = new Date().time;
            do
            {
               checkInterval = 1000;
               while(checkInterval > 0)
               {
                  try
                  {
                     while(checkInterval-- > 0)
                     {
                        cmodule.ccode.gstate.gworker.work();
                     }
                  }
                  catch(e:AlchemyDispatch)
                  {
                  }
               }
            }
            while(new Date().time - startTime < 1000 * 10);
            throw new AlchemyYield();
         }
         catch(e:AlchemyExit)
         {
            timer.stop();
            cmodule.ccode.gstate.system.exit(e.rv);
         }
         catch(e:AlchemyYield)
         {
            ms = int(e.ms);
            timer.delay = ms > 0 ? ms : 1;
         }
         catch(e:AlchemyBlock)
         {
            timer.delay = 10;
         }
         catch(e:AlchemyBreakpoint)
         {
            throw e;
         }
      }
      
      public function startSystemBridge(param1:String, param2:int) : void
      {
         cmodule.ccode.log(3,"bridge: " + param1 + " port: " + param2);
         cmodule.ccode.gstate.system = new CSystemBridge(param1,param2);
         cmodule.ccode.gstate.system.setup(this.startInit);
      }
      
      public function rawAllocString(param1:String) : int
      {
         var _loc2_:int = int(cmodule.ccode.gstate.ds.length);
         cmodule.ccode.gstate.ds.length += param1.length + 1;
         cmodule.ccode.gstate.ds.position = _loc2_;
         var _loc3_:int = 0;
         while(_loc3_ < param1.length)
         {
            cmodule.ccode.gstate.ds.writeByte(param1.charCodeAt(_loc3_));
            _loc3_++;
         }
         cmodule.ccode.gstate.ds.writeByte(0);
         return _loc2_;
      }
      
      public function rawAllocStringArray(param1:Array) : Array
      {
         var _loc2_:Array = [];
         var _loc3_:int = 0;
         while(_loc3_ < param1.length)
         {
            _loc2_.push(this.rawAllocString(param1[_loc3_]));
            _loc3_++;
         }
         return _loc2_;
      }
      
      public function resume() : void
      {
         if(!--this.suspended)
         {
            this.startWork();
         }
      }
      
      public function startSystem() : void
      {
         var request:URLRequest = null;
         var loader:URLLoader = null;
         if(!this.forceSyncSystem)
         {
            request = new URLRequest(".swfbridge");
            loader = new URLLoader();
            loader.dataFormat = URLLoaderDataFormat.TEXT;
            loader.addEventListener(Event.COMPLETE,function(param1:Event):void
            {
               var _loc2_:XML = new XML(loader.data);
               if(Boolean(_loc2_) && Boolean(_loc2_.name() == "bridge") && Boolean(_loc2_.host) && Boolean(_loc2_.port))
               {
                  startSystemBridge(_loc2_.host,_loc2_.port);
               }
               else
               {
                  startSystemLocal();
               }
            });
            loader.addEventListener(IOErrorEvent.IO_ERROR,function(param1:Event):void
            {
               startSystemLocal();
            });
            loader.load(request);
            return;
         }
         this.startSystemLocal(true);
      }
      
      public function rawAllocIntArray(param1:Array) : int
      {
         var _loc2_:int = int(cmodule.ccode.gstate.ds.length);
         cmodule.ccode.gstate.ds.length += (param1.length + 1) * 4;
         cmodule.ccode.gstate.ds.position = _loc2_;
         var _loc3_:int = 0;
         while(_loc3_ < param1.length)
         {
            cmodule.ccode.gstate.ds.writeInt(param1[_loc3_]);
            _loc3_++;
         }
         return _loc2_;
      }
      
      public function startSystemLocal(param1:Boolean = false) : void
      {
         cmodule.ccode.log(3,"local system");
         cmodule.ccode.gstate.system = new CSystemLocal(param1);
         cmodule.ccode.gstate.system.setup(this.startInit);
      }
      
      public function suspend() : void
      {
         ++this.suspended;
         if(Boolean(this.timer) && this.timer.running)
         {
            this.timer.stop();
         }
      }
   }
}

