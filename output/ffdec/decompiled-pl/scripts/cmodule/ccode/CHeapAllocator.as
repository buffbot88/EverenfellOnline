package cmodule.ccode
{
   internal class CHeapAllocator implements ICAllocator
   {
      
      private var pmalloc:Function;
      
      private var pfree:Function;
      
      public function CHeapAllocator()
      {
         super();
      }
      
      public function free(param1:int) : void
      {
         if(this.pfree == null)
         {
            this.pfree = new CProcTypemap(CTypemap.VoidType,[CTypemap.PtrType]).fromC([cmodule.ccode._free]);
         }
         this.pfree(param1);
      }
      
      public function alloc(param1:int) : int
      {
         if(this.pmalloc == null)
         {
            this.pmalloc = new CProcTypemap(CTypemap.PtrType,[CTypemap.IntType]).fromC([cmodule.ccode._malloc]);
         }
         return int(this.pmalloc(param1));
      }
   }
}

