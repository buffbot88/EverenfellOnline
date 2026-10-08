package com.youbt.utils
{
   import flash.display.DisplayObject;
   import flash.utils.getQualifiedClassName;
   
   public class NameUtil
   {
      
      private static var counter:int = 0;
      
      public function NameUtil()
      {
         super();
      }
      
      public static function createUniqueName(param1:Object) : String
      {
         if(!param1)
         {
            return null;
         }
         var _loc2_:String = getQualifiedClassName(param1);
         var _loc3_:int = _loc2_.indexOf("::");
         if(_loc3_ != -1)
         {
            _loc2_ = _loc2_.substr(_loc3_ + 2);
         }
         var _loc4_:int = _loc2_.charCodeAt(_loc2_.length - 1);
         if(_loc4_ >= 48 && _loc4_ <= 57)
         {
            _loc2_ += "_";
         }
         return _loc2_ + counter++;
      }
      
      public static function createUniqueNameByString(param1:String) : String
      {
         var _loc2_:int = param1.charCodeAt(param1.length - 1);
         if(_loc2_ >= 48 && _loc2_ <= 57)
         {
            param1 += "_";
         }
         return param1 + counter++;
      }
      
      public static function getCounter() : int
      {
         return counter++;
      }
      
      public static function displayObjectToString(param1:DisplayObject) : String
      {
         var _loc2_:String = null;
         var _loc4_:String = null;
         var _loc3_:DisplayObject = param1;
         while(_loc3_ != null)
         {
            if(Boolean(_loc3_.parent) && Boolean(_loc3_.stage) && _loc3_.parent == _loc3_.stage)
            {
               break;
            }
            _loc4_ = _loc3_.name;
            _loc2_ = _loc2_ == null ? _loc4_ : _loc4_ + "." + _loc2_;
            _loc3_ = _loc3_.parent;
         }
         return _loc2_;
      }
   }
}

