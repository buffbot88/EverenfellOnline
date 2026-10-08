package com.youbt.manager
{
   import com.youbt.core.Container;
   import flash.display.DisplayObjectContainer;
   import flash.display.Graphics;
   import flash.display.LoaderInfo;
   import flash.display.Sprite;
   import flash.display.Stage;
   import flash.display.StageAlign;
   import flash.display.StageScaleMode;
   import flash.events.Event;
   import flash.events.EventDispatcher;
   import flash.geom.Rectangle;
   
   public class RFSystemManager extends EventDispatcher
   {
      
      private static var _CursorContainer:Container;
      
      private static var _PopupContainer:Container;
      
      private static var _ApplicationContainer:Container;
      
      private static var _MainContainer:Container;
      
      private static var _instance:RFSystemManager;
      
      public static var mouseCatcher:Sprite;
      
      private static var _topLevelSystemManager:*;
      
      public static var stageWidth:int;
      
      public static var stageHeight:int;
      
      private var _topLevel:Boolean;
      
      protected var initialized:Boolean = false;
      
      private var preventEvent:Boolean = false;
      
      private var _screen:Rectangle;
      
      protected var _updateStagewidth:Boolean = true;
      
      private var _stage:Stage;
      
      private var _info:Object = {};
      
      public function RFSystemManager(param1:Stage = null)
      {
         super();
         if(param1)
         {
            param1.scaleMode = StageScaleMode.NO_SCALE;
            param1.align = StageAlign.TOP_LEFT;
         }
         if(RFSystemManagerGlobals.topLevelSystemManagers.length > 0 && !this.stage)
         {
            this._topLevel = false;
         }
         else
         {
            this._topLevel = true;
            _instance = this;
         }
         addEventListener("ba",this.exhandler);
      }
      
      public static function get CursorContainer() : Container
      {
         return _CursorContainer;
      }
      
      public static function get PopupContainer() : Container
      {
         return _PopupContainer;
      }
      
      public static function get ApplicationContainer() : Container
      {
         return _ApplicationContainer;
      }
      
      public static function get MainContainer() : Container
      {
         return _MainContainer;
      }
      
      public static function getInstance(param1:Stage = null) : RFSystemManager
      {
         if(!_instance)
         {
            _instance = new RFSystemManager(param1);
         }
         return _instance;
      }
      
      public function vaildateDisplayList(param1:DisplayObjectContainer) : void
      {
         if(this.initialized == false && Boolean(param1))
         {
            this.initialized = true;
            _MainContainer = new Container();
            _ApplicationContainer = new Container();
            _CursorContainer = new Container();
            _CursorContainer.mouseEnabled = false;
            _PopupContainer = new Container();
            _PopupContainer.mouseEnabled = false;
            mouseCatcher = new Sprite();
            param1.addChild(_MainContainer);
            param1.addChild(_CursorContainer);
            param1.addChildAt(mouseCatcher,0);
            _MainContainer.addChild(_ApplicationContainer);
            _MainContainer.addChild(_PopupContainer);
            _topLevelSystemManager = this;
            if(this.stage)
            {
               this.stage.addEventListener(Event.RESIZE,this.Stage_resizeHandler);
            }
         }
      }
      
      override public function dispatchEvent(param1:Event) : Boolean
      {
         if(this.preventEvent)
         {
            return false;
         }
         return super.dispatchEvent(param1);
      }
      
      public function checkEvent(param1:Event = null) : Boolean
      {
         return !this.preventEvent;
      }
      
      private function exhandler(param1:Event) : void
      {
         if(this.stage)
         {
            while(this.stage.numChildren > 0)
            {
               this.stage.removeChildAt(0);
            }
         }
         this.preventEvent = true;
      }
      
      private function resizeMouseCatcher() : void
      {
         var _loc1_:Graphics = null;
         if(mouseCatcher)
         {
            _loc1_ = mouseCatcher.graphics;
            _loc1_.clear();
            _loc1_.beginFill(983040,0);
            _loc1_.drawRect(0,0,stageWidth,stageHeight);
            _loc1_.endFill();
         }
      }
      
      private function Stage_resizeHandler(param1:Event = null) : void
      {
         if(this._updateStagewidth)
         {
            stageWidth = this.stage.stageWidth;
            stageHeight = this.stage.stageHeight;
         }
         if(param1)
         {
            this.resizeMouseCatcher();
            _instance.dispatchEvent(param1);
         }
      }
      
      public function set updateStagewidth(param1:Boolean) : void
      {
         this._updateStagewidth = param1;
         if(param1)
         {
            this.stage.addEventListener(Event.RESIZE,this.Stage_resizeHandler,false,99999);
            this.Stage_resizeHandler(null);
         }
         else
         {
            this.stage.removeEventListener(Event.RESIZE,this.Stage_resizeHandler);
         }
      }
      
      public function get screen() : Rectangle
      {
         if(!this._screen)
         {
            this.Stage_resizeHandler();
         }
         return this._screen;
      }
      
      public function setStage(param1:Stage) : void
      {
         if(param1)
         {
            this._stage = param1;
            this._updateStagewidth = true;
         }
      }
      
      public function get loaderInfo() : LoaderInfo
      {
         if(this.stage)
         {
            return this.stage.loaderInfo;
         }
         return null;
      }
      
      public function get stage() : Stage
      {
         if(Boolean(!this._topLevel) && Boolean(_topLevelSystemManager) && _topLevelSystemManager.stage is Stage)
         {
            return _topLevelSystemManager.stage;
         }
         return this._stage;
      }
      
      public function set(param1:String, param2:*) : void
      {
         this._info[param1] = param2;
      }
      
      public function get(param1:String) : *
      {
         return this._info[param1];
      }
      
      public function getInfoString() : String
      {
         var _loc2_:String = null;
         var _loc1_:String = "";
         for(_loc2_ in this._info)
         {
            _loc1_ += _loc2_ + "=" + this._info[_loc2_] + ",";
         }
         return _loc1_;
      }
      
      public function remove(param1:String) : void
      {
         this._info[param1] = null;
         delete this._info[param1];
      }
      
      override public function toString() : String
      {
         return "RFSystemManager";
      }
   }
}

