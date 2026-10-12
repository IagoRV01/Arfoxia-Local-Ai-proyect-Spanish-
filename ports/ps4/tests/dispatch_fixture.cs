// Owned host-only fixture. No Sony libraries, UI access, or console payload.
using System;
using System.Collections.Generic;
using System.Threading;

public static class ArfoxiaDispatchFixture
{
    private sealed class Pending
    {
        public SendOrPostCallback Callback;
        public object State;
    }

    private sealed class Context : SynchronizationContext
    {
        public override void Post(SendOrPostCallback callback, object state)
        {
            lock (queue)
            {
                queue.Enqueue(new Pending { Callback = callback, State = state });
                Monitor.PulseAll(queue);
            }
        }
    }

    private static readonly Queue<Pending> queue = new Queue<Pending>();
    private static readonly Context context = new Context();
    private static Thread owner;
    private static bool stopping;
    private static bool ready;

    public static void Initialize()
    {
        owner = new Thread(Run);
        owner.IsBackground = true;
        owner.Start();
        lock (queue)
        {
            while (!ready) Monitor.Wait(queue);
        }
    }

    public static void Enqueue(SendOrPostCallback callback)
    {
        context.Post(callback, null);
    }

    public static bool IsOwnerThread()
    {
        return Thread.CurrentThread == owner;
    }

    public static void Stop()
    {
        lock (queue)
        {
            stopping = true;
            Monitor.PulseAll(queue);
        }
        if (!owner.Join(3000)) throw new InvalidOperationException("Owner did not stop");
    }

    private static void Run()
    {
        SynchronizationContext.SetSynchronizationContext(context);
        lock (queue)
        {
            ready = true;
            Monitor.PulseAll(queue);
        }
        while (true)
        {
            Pending next;
            lock (queue)
            {
                while (queue.Count == 0 && !stopping) Monitor.Wait(queue);
                if (queue.Count == 0 && stopping) return;
                next = queue.Dequeue();
            }
            next.Callback(next.State);
        }
    }
}
