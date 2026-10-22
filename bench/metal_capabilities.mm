// Read-only capability discovery. No performance result is inferred from support.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <mach/mach_time.h>
int main(){ @autoreleasepool {
  id<MTLDevice> d=MTLCreateSystemDefaultDevice();if(!d)return 1;
  NSMutableArray* sets=[NSMutableArray array];
  for(id<MTLCounterSet> s in d.counterSets){
    NSMutableArray* names=[NSMutableArray array];
    for(id<MTLCounter> c in s.counters)[names addObject:c.name];
    [sets addObject:@{@"name":s.name,@"counters":names}];
  }
  mach_timebase_info_data_t tb;mach_timebase_info(&tb);
  NSDictionary* info=@{@"device":d.name,@"registry_id":@(d.registryID),
    @"unified_memory":@(d.hasUnifiedMemory),@"max_buffer_bytes":@(d.maxBufferLength),
    @"recommended_working_set_bytes":@(d.recommendedMaxWorkingSetSize),
    @"current_allocated_bytes":@(d.currentAllocatedSize),@"counter_sets":sets,
    @"dispatch_boundary_sampling":@([d supportsCounterSampling:MTLCounterSamplingPointAtDispatchBoundary]),
    @"stage_boundary_sampling":@([d supportsCounterSampling:MTLCounterSamplingPointAtStageBoundary]),
    @"mach_seconds":@(mach_absolute_time()*1e-9*tb.numer/tb.denom)};
  NSData* json=[NSJSONSerialization dataWithJSONObject:info options:NSJSONWritingPrettyPrinted error:nil];
  fwrite(json.bytes,1,json.length,stdout);puts("");
} }
