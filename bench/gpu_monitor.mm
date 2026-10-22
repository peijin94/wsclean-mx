// Device-wide IORegistry gauges + selected-process cumulative counters.
// Registry utilization is NOT shader occupancy or per-process GPU utilization.
#import <Foundation/Foundation.h>
#include <IOKit/IOKitLib.h>
#include <dispatch/dispatch.h>
#include <mach/mach_time.h>
#include <libproc.h>
#include <sys/resource.h>
#include <unistd.h>
#include <cerrno>
#include <cstdlib>
#include <cstdio>
int main(int argc,char**argv){@autoreleasepool{
  if(argc!=4){fprintf(stderr,"usage: gpu-monitor interval_ms duration_ms pid(0=device-only)\n");return 2;}
  char *e1,*e2,*e3;long interval=strtol(argv[1],&e1,10),duration=strtol(argv[2],&e2,10),pid=strtol(argv[3],&e3,10);
  if(*e1||*e2||*e3||interval<10||interval>10000||duration<interval||duration>3600000||pid<0){return 2;}
  io_iterator_t it=0;
  if(IOServiceGetMatchingServices(kIOMainPortDefault,IOServiceMatching("IOAccelerator"),&it)!=KERN_SUCCESS)return 3;
  io_service_t service=IOIteratorNext(it);IOObjectRelease(it);if(!service)return 3;
  mach_timebase_info_data_t tb;mach_timebase_info(&tb);
  double scale=1e-9*double(tb.numer)/tb.denom;
  double begin=mach_absolute_time()*scale;
  dispatch_source_t timer=dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER,0,0,dispatch_get_main_queue());
  dispatch_source_set_timer(timer,dispatch_time(DISPATCH_TIME_NOW,0),uint64_t(interval)*1000000,1000000);
  dispatch_source_set_event_handler(timer,^{@autoreleasepool{
    double now=mach_absolute_time()*scale;
    if(now-begin>=double(duration)/1000){IOObjectRelease(service);exit(0);}
    CFTypeRef property=IORegistryEntryCreateCFProperty(service,CFSTR("PerformanceStatistics"),kCFAllocatorDefault,0);
    NSDictionary* stats=CFBridgingRelease(property);
    NSMutableDictionary* row=[NSMutableDictionary dictionaryWithDictionary:@{@"mach_s":@(now),@"unix_s":@([[NSDate date] timeIntervalSince1970]),@"pid":@(pid)}];
    if([stats isKindOfClass:[NSDictionary class]]){
      for(NSString* key in @[@"Device Utilization %",@"Renderer Utilization %",@"Tiler Utilization %",@"Alloc system memory",@"In use system memory",@"In use system memory (driver)"])
        if(stats[key])row[key]=stats[key];
    }else row[@"registry_error"]=@YES;
    if(pid){
      struct rusage_info_v4 ri={};
      if(proc_pid_rusage(pid,RUSAGE_INFO_V4,(rusage_info_t*)&ri)==0){
        // proc_pid_rusage reports Mach absolute ticks, not nanoseconds.
        row[@"cpu_user_ticks"]=@(ri.ri_user_time);row[@"cpu_system_ticks"]=@(ri.ri_system_time);
        row[@"cpu_user_s"]=@(ri.ri_user_time*scale);row[@"cpu_system_s"]=@(ri.ri_system_time*scale);
        row[@"mach_tick_seconds"]=@(scale);
        row[@"instructions"]=@(ri.ri_instructions);row[@"cycles"]=@(ri.ri_cycles);
        row[@"resident_bytes"]=@(ri.ri_resident_size);row[@"footprint_bytes"]=@(ri.ri_phys_footprint);
        row[@"pageins"]=@(ri.ri_pageins);row[@"disk_read_bytes"]=@(ri.ri_diskio_bytesread);row[@"disk_write_bytes"]=@(ri.ri_diskio_byteswritten);
      }else row[@"process_error"]=@(errno);
    }
    row[@"query_end_mach_s"]=@(mach_absolute_time()*scale);
    NSData* data=[NSJSONSerialization dataWithJSONObject:row options:0 error:nil];
    if(!data){IOObjectRelease(service);exit(4);}
    fwrite(data.bytes,1,data.length,stdout);putchar('\n');fflush(stdout);
  }});
  // A parent may stop collection by sending a byte or closing its pipe.
  dispatch_source_t stop=dispatch_source_create(DISPATCH_SOURCE_TYPE_READ,STDIN_FILENO,0,dispatch_get_main_queue());
  dispatch_source_set_event_handler(stop,^{char c;read(STDIN_FILENO,&c,1);IOObjectRelease(service);exit(0);});
  dispatch_resume(stop);dispatch_resume(timer);dispatch_main();
}}
