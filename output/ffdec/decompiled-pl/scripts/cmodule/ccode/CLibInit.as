package cmodule.ccode
{
   import flash.display.*;
   import flash.events.*;
   import flash.net.*;
   import flash.system.*;
   import flash.text.*;
   import flash.utils.*;
   
   public class CLibInit
   {
      
      public function CLibInit()
      {
         super();
      }
      
      public function init() : *
      {
         var result:* = undefined;
         var regged:Boolean = false;
         var runner:CRunner = new CRunner(true);
         var saveState:MState = new MState(null);
         cmodule.ccode.mstate.copyTo(saveState);
         try
         {
            try
            {
               runner.startSystem();
               while(true)
               {
                  try
                  {
                     while(true)
                     {
                        runner.work();
                     }
                  }
                  catch(e:AlchemyDispatch)
                  {
                  }
                  catch(e:AlchemyYield)
                  {
                  }
               }
            }
            catch(e:AlchemyLibInit)
            {
               cmodule.ccode.log(3,"Caught AlchemyLibInit " + e.rv);
               regged = true;
               result = CTypemap.AS3ValType.valueTracker.release(e.rv);
            }
            return result;
         }
         finally
         {
            saveState.copyTo(cmodule.ccode.mstate);
            if(!regged)
            {
               cmodule.ccode.log(1,"Lib didn\'t register");
            }
         }
      }
      
      public function supplyFile(param1:String, param2:ByteArray) : void
      {
         cmodule.ccode.gfiles[param1] = param2;
      }
      
      public function putEnv(param1:String, param2:String) : void
      {
         cmodule.ccode.genv[param1] = param2;
      }
      
      public function setSprite(param1:Sprite) : void
      {
         cmodule.ccode.gsprite = param1;
      }
   }
}

