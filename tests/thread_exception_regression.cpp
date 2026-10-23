// Standalone contract test for the production ducc0 scheduler. No sleeps:
// workers wait at a condition-variable gate with a bounded deadline. On a
// broken scheduler, exit before releasing workers into destroyed stack state.
#include "ducc0/infra/threading.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <new>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

namespace {
struct SubmissionGate {
  std::mutex mutex;
  std::condition_variable cv;
  size_t entered = 0, completed = 0;
  bool rejected = false;
  const std::chrono::steady_clock::time_point deadline =
      std::chrono::steady_clock::now()+std::chrono::seconds(5);
  void reject() {
    std::lock_guard<std::mutex> lock(mutex);
    rejected = true;
    cv.notify_all();
  }
};
// Armed only on the submitting thread, after an accepted job has entered its
// callback. The next allocation is the next submission's std::function storage.
thread_local SubmissionGate* fail_next_allocation = nullptr;
}

void* operator new(std::size_t size) {
  if (auto* gate = std::exchange(fail_next_allocation, nullptr)) {
    gate->reject();
    throw std::bad_alloc();
  }
  if (void* ptr = std::malloc(size ? size : 1)) return ptr;
  throw std::bad_alloc();
}
void operator delete(void* ptr) noexcept { std::free(ptr); }
void* operator new[](std::size_t size) { return ::operator new(size); }
void operator delete[](void* ptr) noexcept { ::operator delete(ptr); }
#ifdef __cpp_sized_deallocation
void operator delete(void* ptr, std::size_t) noexcept { std::free(ptr); }
void operator delete[](void* ptr, std::size_t) noexcept { std::free(ptr); }
#endif

namespace {
struct CallbackError : std::runtime_error {
  using std::runtime_error::runtime_error;
};
void require(bool ok, const std::string& message) {
  if (!ok) {
    std::cerr << "FAIL " << message << std::endl;
    std::_Exit(1);
  }
}
// Bounds even a scheduler stuck waiting for submissions that were not accepted.
class Watchdog {
  std::mutex mutex;
  std::condition_variable cv;
  bool done = false;
  std::thread thread;
 public:
  Watchdog() : thread([this] {
    std::unique_lock<std::mutex> lock(mutex);
    require(cv.wait_for(lock, std::chrono::seconds(5), [&]{ return done; }),
            "scheduler exceeded bounded watchdog");
  }) {}
  ~Watchdog() {
    {
      std::lock_guard<std::mutex> lock(mutex);
      done = true;
      cv.notify_all();
    }
    thread.join();
  }
};
struct SubmissionError : std::runtime_error {
  const void* payload;
  explicit SubmissionError(const void* value)
      : std::runtime_error("submission payload"), payload(value) {}
};
class RejectingPool : public ducc0::detail_threading::thread_pool {
  SubmissionGate& gate;
  size_t reject_at;
  bool allocation_failure;
  std::vector<std::thread> workers;
 public:
  size_t attempts = 0;
  RejectingPool(SubmissionGate& gate_, size_t reject_at_, bool allocation_failure_)
      : gate(gate_), reject_at(reject_at_), allocation_failure(allocation_failure_) {
    workers.reserve(3);
  }
  ~RejectingPool() { for (auto& worker : workers) worker.join(); }
  size_t nthreads() const override { return 3; }
  size_t adjust_nthreads(size_t n) const override { return n == 0 ? 4 : std::min(n, size_t(4)); }
  void submit(std::function<void()> work) override {
    ++attempts;
    // Contract: rejection throws BEFORE this job is accepted or executed.
    if (!allocation_failure && attempts == reject_at) {
      gate.reject();
      throw SubmissionError(&gate);
    }
    workers.emplace_back(std::move(work));
    {
      std::unique_lock<std::mutex> lock(gate.mutex);
      require(gate.cv.wait_until(lock, gate.deadline,
                               [&]{ return gate.entered == attempts; }),
              "accepted worker entered callback before next submission");
    }
    if (allocation_failure && attempts+1 == reject_at)
      fail_next_allocation = &gate;
  }
  void allow_reuse() {
    for (auto& worker : workers) worker.join();
    workers.clear();
    reject_at = 0;
    allocation_failure = false;
    attempts = 0;
    std::lock_guard<std::mutex> lock(gate.mutex);
    gate.entered = 0;
  }
};
using Callback = std::function<void(ducc0::Scheduler&)>;
void execute(const std::string& mode, Callback callback) {
  if (mode == "dynamic") ducc0::execDynamic(64, 4, 1, callback);
  else if (mode == "static") ducc0::execStatic(64, 4, 1, callback);
  else if (mode == "guided") ducc0::execGuided(64, 4, 1, .5, callback);
  else ducc0::execParallel(4, callback);
}
void exceptional_submission(const std::string& mode, size_t reject_at,
                            bool allocation_failure, bool worker_throws = false) {
  Watchdog watchdog;
  SubmissionGate gate;
  RejectingPool pool(gate, reject_at, allocation_failure);
  ducc0::detail_threading::ScopedUseThreadPool use_pool(pool);
  bool caught = false;
  size_t caller_calls = 0;
  try {
    execute(mode, [&, partials = std::vector<size_t>(4)](ducc0::Scheduler& sched) mutable {
      if (sched.thread_num() == 0) { ++caller_calls; return; }
      {
        std::unique_lock<std::mutex> lock(gate.mutex);
        ++gate.entered;
        gate.cv.notify_all();
        require(gate.cv.wait_until(lock, gate.deadline, [&]{ return gate.rejected; }),
                "submission failure reached");
        // Keep accepted callbacks active across delivery of the submission
        // exception. All synchronization, including this hold, is bounded.
        gate.cv.wait_until(lock, std::chrono::steady_clock::now()+std::chrono::milliseconds(250),
                           []{ return false; });
      }
      require(sched.num_threads() == 4, "distribution alive while draining");
      if (mode != "parallel") while (sched.getNext()) {}
      ++partials[sched.thread_num()];
      {
        std::lock_guard<std::mutex> lock(gate.mutex);
        ++gate.completed;
      }
      if (worker_throws) throw CallbackError("worker during rejection");
    });
  } catch (const SubmissionError& e) {
    caught = !allocation_failure && e.payload == &gate &&
             std::string(e.what()) == "submission payload";
  } catch (const std::bad_alloc&) {
    caught = allocation_failure && fail_next_allocation == nullptr;
  }
  require(caught, "submission exception type/payload preserved");
  {
    std::lock_guard<std::mutex> lock(gate.mutex);
    require(gate.completed == reject_at-1, "submission rethrew before accepted workers drained");
  }
  require(pool.attempts == reject_at-(allocation_failure ? 1 : 0),
          "failure occurred at selected submission boundary");
  require(caller_calls == 0, "caller callback skipped after submission failure");
  pool.allow_reuse();
  // Use the same pool again, exercising ordinary dispatch and work coverage.
  std::atomic<size_t> count{0};
  execute(mode, [&](ducc0::Scheduler& sched) {
    if (sched.thread_num() != 0) {
      std::lock_guard<std::mutex> lock(gate.mutex);
      ++gate.entered;
      gate.cv.notify_all();
    }
    if (mode == "parallel") ++count;
    else while (auto range = sched.getNext()) count += range.hi-range.lo;
  });
  require(count == (mode == "parallel" ? 4 : 64), "same rejecting pool reusable after exception");
  std::cout << "PASS " << mode << (allocation_failure ? " construction" : " rejection")
            << " submission=" << reject_at << " drained=" << gate.completed
            << " worker_throws=" << worker_throws << " reuse=" << count << '\n';
}
void exceptional_caller(const std::string& mode) {
  std::mutex mutex;
  std::condition_variable cv;
  size_t entered = 0, completed = 0;
  bool throwing = false;
  bool caught = false;
  const auto deadline = std::chrono::steady_clock::now()+std::chrono::seconds(5);
  try {
    execute(mode, [&](ducc0::Scheduler& sched) {
      std::unique_lock<std::mutex> lock(mutex);
      if (sched.thread_num() == 0) {
        require(cv.wait_until(lock, deadline, [&]{ return entered == 3; }),
                mode+" workers entered before caller exception");
        throwing = true;
        cv.notify_all();
        throw CallbackError("caller payload");
      }
      ++entered;
      cv.notify_all();
      require(cv.wait_until(lock, deadline, [&]{ return throwing; }),
              mode+" caller reached exception");
      // Hold workers across the throw. A correct scheduler drains them before
      // delivering the exception. This is a CV deadline, not a busy wait or
      // sleep; no assertion requires completion within a scheduling interval.
      cv.wait_until(lock, std::chrono::steady_clock::now()+std::chrono::milliseconds(250),
                    []{ return false; });
      // Exercise the scheduler state *after* the invoking callback has thrown.
      if (mode != "parallel") while (sched.getNext()) {}
      ++completed;
    });
  } catch (const CallbackError& e) {
    caught = std::string(e.what()) == "caller payload";
    std::lock_guard<std::mutex> lock(mutex);
    require(completed == 3, mode+" rethrew before workers drained");
  }
  require(caught, mode+" caller exception type/payload preserved");
  std::cout << "PASS " << mode << " caller exception drained=" << completed << '\n';
}
void exceptional_worker(const std::string& mode) {
  bool caught = false;
  try {
    execute(mode, [&](ducc0::Scheduler& sched) {
      if (sched.thread_num() == 1) throw CallbackError("worker payload");
      if (mode != "parallel") while (sched.getNext()) {}
    });
  } catch (const CallbackError& e) {
    caught = std::string(e.what()) == "worker payload";
  }
  require(caught, mode+" worker exception type/payload preserved");
  std::atomic<size_t> count{0};
  execute(mode, [&](ducc0::Scheduler& sched) {
    if (mode == "parallel") ++count;
    else while (auto range = sched.getNext()) count += range.hi-range.lo;
  });
  require(count == (mode == "parallel" ? 4 : 64), mode+" pool reusable after exception");
}
} // namespace
int main(int argc, char** argv) {
  if (argc > 1 && std::string(argv[1]) == "--submission") {
    require(argc == 5, "usage: --submission MODE INDEX reject|allocation|worker");
    exceptional_submission(argv[2], std::stoul(argv[3]),
                           std::string(argv[4]) == "allocation",
                           std::string(argv[4]) == "worker");
    return 0;
  }
  for (const std::string mode : {"dynamic", "static", "guided", "parallel"}) {
    if (argc > 1 && mode != argv[1]) continue;
    exceptional_caller(mode);
    exceptional_worker(mode);
    for (size_t reject_at : {1, 2, 3})
      exceptional_submission(mode, reject_at, false);
    for (size_t reject_at : {2, 3})
      exceptional_submission(mode, reject_at, true);
    exceptional_submission(mode, 3, false, true);
  }
  std::cout << "PASS scheduler exception contracts\n";
}
