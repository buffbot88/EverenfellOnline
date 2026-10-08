package com.youbt.events
{
   import flash.events.Event;
   
   public class RFEvent extends Event
   {
      
      public static const ADD:String = "add";
      
      public static const LOADING_COMPLETE:String = "loadingComplete";
      
      public static const CREATION_COMPLETE:String = "creationComplete";
      
      public static const CURSOR_UPDATE:String = "cursorUpdate";
      
      public static const HIDE:String = "hide";
      
      public static const IDLE:String = "idle";
      
      public static const INIT_COMPLETE:String = "initComplete";
      
      public static const INIT_PROGRESS:String = "initProgress";
      
      public static const INITIALIZE:String = "initialize";
      
      public static const LOADING:String = "loading";
      
      public static const PREINITIALIZE:String = "preinitialize";
      
      public static const REMOVE:String = "remove";
      
      public static const SHOW:String = "show";
      
      public var isPlugin:Boolean;
      
      public function RFEvent(param1:String, param2:Boolean = false, param3:Boolean = false, param4:Boolean = false)
      {
         super(param1,param3,param4);
         this.isPlugin = param2;
      }
      
      override public function clone() : Event
      {
         return new RFEvent(type,this.isPlugin,bubbles,cancelable);
      }
   }
}

